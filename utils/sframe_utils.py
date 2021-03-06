from collections import Counter
import pandas as pd
import numpy as np
import sys, os

import turicreate as tc
import turicreate.aggregate as agg

### General SFrame functions ###

def dtypes(sf):
    return list(zip(sf.column_names(), sf.dtype))

def replace(sf, replace_dict, cols=None):
    sf_tmp = sf.copy()
    if cols == None:
        cols = sf_tmp.column_names()
    for c in cols:
        sf_tmp[c] = sf_tmp[c].apply(lambda x: replace_dict.get(x,x))
    return sf_tmp

def fillna(sf, value, cols=None):
    if cols == None:
        cols = sf.column_names()
    for c in cols:
        sf = sf.fillna(c, value)
    return sf

def drop_columns(sf, columns):
    sf_tmp = sf.copy()
    for col in columns:
        sf_tmp = sf_tmp.remove_column(col)
    return sf_tmp

def concatenate(s1, s2):
    diff_1 = list(set(dtypes(s1)) - set(dtypes(s2)))
    #print(diff_1)
    for col, t in diff_1:
        s2[col] = None
        s2[col] = s2[col].astype(t)
    diff_2 = list(set(dtypes(s2)) - set(dtypes(s1)))
    #print(diff_2)
    for col, t in diff_2:
        s1[col] = None
        s1[col] = s1[col].astype(t)
    union = list(set(s2.column_names()).union(set(s1.column_names())))
    #print(union)
    return s1[union].append(s2[union])
        
def get_dummies(sf, columns, keep=False, selected_columns=None):
    sf_tmp = sf.copy()
    for col in columns:
        unique_values = list(sf[col].unique())
        for col_val in unique_values:
            new_col = col + "_ONEHOT_" + str(col_val)
            if selected_columns == None or new_col  in selected_columns:
                sf_tmp[new_col] = sf_tmp.apply(lambda x: 1 if x[col] == col_val else 0)
        if not keep:
            sf_tmp = sf_tmp.remove_column(col)
        print(col)
    return sf_tmp

def value_counts(sf, col):
    return Counter(list(sf[col])).most_common()

def num_missing(sf, cols=None):
    if cols == None:
        cols = sf.column_names()
    missing_info = []
    for c in cols:
        if None in sf[c]:
            cnt_info = sf[c].value_counts()
            num_missing = cnt_info[cnt_info["value"] == None]["count"][0]
            missing_info.append((c, num_missing))
            print(c)
    missing_df = pd.DataFrame(missing_info, columns=["name","num_missing"]).sort_values("num_missing", ascending=False)
    missing_df["frac_missing"] = missing_df["num_missing"] / len(sf)
    return missing_df

#def batch_join(left, right, keys, how="left", batch_size=10000000):
def batch_join(left, right, keys, how="left", batch_size=20000000):
    if len(left) <= batch_size:
        print("default join is applied!")
        return left.join(right, on=keys, how=how)
    else:
        print("batch join is applied!")
        index_splits = list(range(0, len(left)+batch_size, batch_size))
        is_first = True
        for i in range(1, len(index_splits)):
            from_idx, to_idx = index_splits[i-1], index_splits[i]
            partial_left = left[from_idx:to_idx]
            if is_first:
                joined = partial_left.join(right, on=keys, how=how)
                is_first = False
            else:
                joined = joined.append(partial_left.join(right, on=keys, how=how))
            print(i, len(joined))
        return joined

### Data transformations ###

def process_skip_information(sf, exec_onehot=True):
    sf["target"] = sf.apply(lambda x: 1 if x["skip"] > 1 else 0)
    if exec_onehot:
        sf = get_dummies(sf, columns=["skip"], keep=True)
        sf = sf.rename({"skip_ONEHOT_1": "skip_1", "skip_ONEHOT_2": "skip_2", "skip_ONEHOT_3": "skip_3", "skip_ONEHOT_0": "not_skipped"})
    return sf

def separate_session(sf, eval_enabled_columns):
    sf["is_first_part"] = sf.apply(lambda x: x["session_position"] <= x["session_length"] // 2)
    first_part_data = sf.filter_by(True, "is_first_part", exclude=False)
    second_part_data = sf.filter_by(True, "is_first_part", exclude=True)
    sf = sf.remove_column("is_first_part")
    first_part_data = first_part_data.remove_column("is_first_part")
    #second_part_data = second_part_data.remove_column("is_first_part")
    second_part_data = second_part_data[eval_enabled_columns]
    print(first_part_data.shape, second_part_data.shape)
    return first_part_data, second_part_data

def get_agg_cols(postfix, agg_type, agg_cols=['not_skipped', 'skip_1', 'skip_2', 'skip_3']):
    if agg_type == "mean":
        return {("%s_mean_%s" % (col, postfix)) : agg.MEAN(col) for col in agg_cols}
    elif agg_type == "sum":
        return {("%s_sum_%s" % (col, postfix)) : agg.SUM(col) for col in agg_cols}
    elif agg_type == "count":
        return {("cnt_%s" % postfix) : agg.COUNT()}
    else:
        raise RuntimeError("Aggregation is not supported by this function!")
        
def aggregate_track_info(sf, keys, postfix):
    aggs = {}
    aggs.update(get_agg_cols(postfix, "mean"))
    aggs.update(get_agg_cols(postfix, "sum"))
    aggs.update(get_agg_cols(postfix, "count"))
    return sf.groupby(keys, operations=aggs)