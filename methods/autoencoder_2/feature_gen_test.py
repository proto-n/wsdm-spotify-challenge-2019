import pandas as pd
import gc
import numpy as np
import matplotlib.pyplot as plt
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import math
import sklearn.metrics
from glob import glob
import sys

split_folder = sys.argv[1]

device = "cpu:0"
saved = torch.load(split_folder + "/models/autoencoder_2", map_location='cpu')

max_track = 3706391


encoder = nn.Embedding(int(max_track + 1), embedding_dim=128, sparse=True, padding_idx=torch.LongTensor([0])[0]).to(device)
decoder = nn.Embedding(int(max_track + 1), embedding_dim=128, sparse=True, padding_idx=torch.LongTensor([0])[0]).to(device)

layers = 2
lstm = nn.LSTM(input_size=128, hidden_size=256, num_layers=layers, batch_first=True, dropout=0, bidirectional=False)
lstm.flatten_parameters()
lstm.to(device)
out_lin1 = nn.Linear(256, 256).to(device)
out_lin2 = nn.Linear(256, 128).to(device)

encoder.load_state_dict(saved['encoder'])
decoder.load_state_dict(saved['decoder'])
lstm.load_state_dict(saved['lstm'])
out_lin1.load_state_dict(saved['out_lin1'])
out_lin2.load_state_dict(saved['out_lin2'])


del saved
gc.collect()


inp_files = sorted(glob(split_folder + "/test/log_input_*"))
pre_files = sorted(glob(split_folder + "/test/log_prehistory_*"))


def data_iter(f, ll, bsize, round_batch=False):
    fbsize = bsize * 20
    alternating = np.zeros(bsize * 2)
    alternating[::2] = 1

    findex = f * ll * 20
    if round_batch:
        tindex = min(len(combined_fixed_length) - len(combined_fixed_length) % fbsize, (f + 1) * ll * 20)
    else:
        tindex = min(len(combined_fixed_length), (f + 1) * ll * 20)

        leftover = (len(combined_fixed_length) // 20) % bsize
        alternating_last = np.zeros(leftover * 2)
        alternating_last[::2] = 1

    for i in range(findex, tindex, fbsize):
        batch = combined_fixed_length[i:i + fbsize].reshape(-1, 20)
        items = np.abs(batch).astype(np.int64)
        targets = np.sign(batch).astype(np.float32)
        mask_l = (targets != 0).sum(axis=1) // 2
        mask_cl = 20 - mask_l
        if batch.shape[0] == bsize:
            mask = np.repeat(alternating, np.column_stack([mask_l, mask_cl]).ravel()).reshape(-1, 20).astype(np.int64)
            yield (items, targets, mask)
        else:
            mask = np.repeat(alternating_last, np.column_stack([mask_l, mask_cl]).ravel()).reshape(-1, 20).astype(np.int64)
            yield (items, targets, mask)


for(inp_full_name, pre_full_name) in zip(inp_files, pre_files):
    print(inp_full_name)

    inp_full = pd.read_pickle(inp_full_name)
    pre_full = pd.read_pickle(pre_full_name)

    inp_session_codes = inp_full.session_code.values
    prehist_session_codes = pre_full.session_code.values

    prehist_split_indices = np.where(np.ediff1d(prehist_session_codes))[0] + 1
    inp_split_indices = np.where(np.ediff1d(inp_session_codes))[0] + 1

    prehist_signed_track_values = pre_full['track_code'].values * ((pre_full['skip'].values >= 2) * 2 - 1)
    inp_track_values = inp_full['track_code'].values

    session_lengths = inp_full['session_length'].values[np.concatenate([[0], inp_split_indices])]
    zero_lengths = 20 - session_lengths

    zero_pads = np.split(np.zeros(zero_lengths.sum()), np.cumsum(zero_lengths))[:-1]
    prehist_signed_track_values_split = np.split(prehist_signed_track_values, prehist_split_indices)
    inp_track_values_split = np.split(inp_track_values, inp_split_indices)

    correct_order = [i for t in zip(prehist_signed_track_values_split, inp_track_values_split, zero_pads) for i in t]
    combined_fixed_length = np.concatenate(correct_order)

    out_scores_batches = []
    for i in range(25):
        print(i, end=" ", flush=True)
        iterator = data_iter(i, 1000000, 10)

        for (items, targets, train_mask) in iterator:
            with torch.no_grad():
                items_torch = torch.from_numpy(items).to(device)
                mask = torch.from_numpy(train_mask).to(device)
                targets_torch = torch.from_numpy(targets).to(device)
                # in_embeds = encoder(items_torch * mask)
                in_embeds = F.dropout(encoder(items_torch * mask), 0.2)
                out_embeds = F.dropout(decoder(items_torch), 0.2)

                h0 = torch.zeros(layers, items_torch.shape[0], 256).to(device)
                c0 = torch.zeros(layers, items_torch.shape[0], 256).to(device)
                res = lstm(in_embeds * targets_torch.unsqueeze(2), (c0, h0))
                res2 = out_lin2(F.relu(out_lin1(res[0])))
                scores = (res2 * out_embeds).sum(2)

                scores_np = scores.detach().cpu().numpy().reshape(-1)

                test_mask = (items != 0) & (1 - train_mask)
                targets_ = (targets.reshape(-1)[test_mask.reshape(-1) != 0] + 1) / 2
                scores_ = scores_np[test_mask.reshape(-1) != 0]
                out_scores_batches.append(scores_)
    out_scores = np.concatenate(out_scores_batches)

    inp_full['autoencoder_2_pred'] = out_scores

    fname = split_folder + '/features/test/autoencoder_2_' + inp_full_name[len(split_folder + "/test/log_input_"):]
    inp_full[['autoencoder_2_pred']].to_pickle(fname)
