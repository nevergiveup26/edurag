# -*- coding: utf-8 -*-
'''
CMRC 2018 Evaluation Script — Python 3 port

Original: cmrc2018/squad-style-data/cmrc2018_evaluate.py (v5)
Fixed: removed py2 reload(sys), .decode('utf-8'), ur'...' syntax
'''
from collections import OrderedDict
import re
import sys
import json


def mixed_segmentation(in_str, rm_punc=False):
    """Split Chinese text with English words"""
    in_str = in_str.lower().strip()
    segs_out = []
    temp_str = ""
    sp_char = ['-', ':', '_', '*', '^', '/', '\\', '~', '`', '+', '=',
               '，', '。', '：', '？', '！', '"', '"', '；', '’', '《', '》', '……', '·', '、',
               '「', '」', '（', '）', '－', '～', '『', '』']
    for char in in_str:
        if rm_punc and char in sp_char:
            continue
        if re.search(r'[一-龥]', char) or char in sp_char:
            if temp_str != "":
                # simple English tokenization: split on whitespace
                ss = temp_str.split()
                segs_out.extend(ss)
                temp_str = ""
            segs_out.append(char)
        else:
            temp_str += char

    if temp_str != "":
        ss = temp_str.split()
        segs_out.extend(ss)

    return segs_out


def remove_punctuation(in_str):
    """Remove Chinese and English punctuation"""
    in_str = in_str.lower().strip()
    sp_char = ['-', ':', '_', '*', '^', '/', '\\', '~', '`', '+', '=',
               '，', '。', '：', '？', '！', '"', '"', '；', '’', '《', '》', '……', '·', '、',
               '「', '」', '（', '）', '－', '～', '『', '』']
    out_segs = []
    for char in in_str:
        if char in sp_char:
            continue
        else:
            out_segs.append(char)
    return ''.join(out_segs)


def find_lcs(s1, s2):
    """Find longest common substring"""
    m = [[0 for i in range(len(s2) + 1)] for j in range(len(s1) + 1)]
    mmax = 0
    p = 0
    for i in range(len(s1)):
        for j in range(len(s2)):
            if s1[i] == s2[j]:
                m[i + 1][j + 1] = m[i][j] + 1
                if m[i + 1][j + 1] > mmax:
                    mmax = m[i + 1][j + 1]
                    p = i + 1
    return s1[p - mmax:p], mmax


def evaluate(ground_truth_file, prediction_file):
    """
    Evaluate CMRC predictions.

    Args:
        ground_truth_file: SQuAD-format dict {"data": [{"paragraphs": [...]}]}
        prediction_file: dict mapping query_id -> prediction_text

    Returns:
        (f1_score, em_score, total_count, skip_count)
    """
    f1 = 0
    em = 0
    total_count = 0
    skip_count = 0

    for instance in ground_truth_file["data"]:
        for para in instance["paragraphs"]:
            for qas in para['qas']:
                total_count += 1
                query_id = qas['id'].strip()
                answers = [x["text"] for x in qas['answers']]

                if query_id not in prediction_file:
                    sys.stderr.write('Unanswered question: {}\n'.format(query_id))
                    skip_count += 1
                    continue

                prediction = str(prediction_file[query_id])
                f1 += calc_f1_score(answers, prediction)
                em += calc_em_score(answers, prediction)

    f1_score = 100.0 * f1 / total_count if total_count > 0 else 0
    em_score = 100.0 * em / total_count if total_count > 0 else 0
    return f1_score, em_score, total_count, skip_count


def calc_f1_score(answers, prediction):
    """Calculate F1 score for a single prediction"""
    f1_scores = []
    for ans in answers:
        ans_segs = mixed_segmentation(ans, rm_punc=True)
        prediction_segs = mixed_segmentation(prediction, rm_punc=True)
        lcs, lcs_len = find_lcs(ans_segs, prediction_segs)
        if lcs_len == 0:
            f1_scores.append(0)
            continue
        precision = 1.0 * lcs_len / len(prediction_segs)
        recall = 1.0 * lcs_len / len(ans_segs)
        f1 = (2 * precision * recall) / (precision + recall)
        f1_scores.append(f1)
    return max(f1_scores)


def calc_em_score(answers, prediction):
    """Calculate Exact Match score for a single prediction"""
    em = 0
    for ans in answers:
        ans_ = remove_punctuation(ans)
        prediction_ = remove_punctuation(prediction)
        if ans_ == prediction_:
            em = 1
            break
    return em
