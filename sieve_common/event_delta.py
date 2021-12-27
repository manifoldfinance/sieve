import copy
from typing import Dict, List, Tuple, Optional, Set
from sieve_common.common import *


def diff_event_as_list(
    prev_event: List, cur_event: List
) -> Tuple[Optional[List], Optional[List]]:
    prev_len = len(prev_event)
    cur_len = len(cur_event)
    min_len = min(prev_len, cur_len)
    diff_prev_event = [SIEVE_IDX_SKIP] * prev_len
    diff_cur_event = [SIEVE_IDX_SKIP] * cur_len
    for i in range(min_len):
        if isinstance(cur_event[i], dict):
            if not isinstance(prev_event[i], dict):
                diff_prev_event[i] = prev_event[i]
                diff_cur_event[i] = cur_event[i]
            else:
                sub_diff_prev_event, sub_diff_cur_event = diff_event_as_map(
                    prev_event[i], cur_event[i]
                )
                if sub_diff_prev_event is None or sub_diff_cur_event is None:
                    continue
                diff_prev_event[i] = sub_diff_prev_event
                diff_cur_event[i] = sub_diff_cur_event
        elif isinstance(cur_event[i], list):
            if not isinstance(prev_event[i], list):
                diff_prev_event[i] = prev_event[i]
                diff_cur_event[i] = cur_event[i]
            else:
                sub_diff_prev_event, sub_diff_cur_event = diff_event_as_list(
                    prev_event[i], cur_event[i]
                )
                if sub_diff_prev_event is None or sub_diff_cur_event is None:
                    continue
                diff_prev_event[i] = sub_diff_prev_event
                diff_cur_event[i] = sub_diff_cur_event
        else:
            if prev_event[i] != cur_event[i]:
                diff_prev_event[i] = prev_event[i]
                diff_cur_event[i] = cur_event[i]
    if prev_len > min_len:
        for i in range(min_len, prev_len):
            diff_prev_event[i] = prev_event[i]
    if cur_len > min_len:
        for i in range(min_len, cur_len):
            diff_cur_event[i] = cur_event[i]
    if cur_len == prev_len:
        keep = False
        for i in range(cur_len):
            if (
                not diff_prev_event[i] == SIEVE_IDX_SKIP
                or not diff_cur_event[i] == SIEVE_IDX_SKIP
            ):
                keep = True
        if not keep:
            return None, None
    return diff_prev_event, diff_cur_event


def diff_event_as_map(
    prev_event: Dict, cur_event: Dict
) -> Tuple[Optional[Dict], Optional[Dict]]:
    diff_prev_event = {}
    diff_cur_event = {}

    common_keys = set(cur_event.keys()).intersection(prev_event.keys())
    pdc_keys = set(prev_event.keys()).difference(cur_event.keys())
    cdp_keys = set(cur_event.keys()).difference(prev_event.keys())
    for key in common_keys:
        if isinstance(cur_event[key], dict):
            if not isinstance(prev_event[key], dict):
                diff_prev_event[key] = prev_event[key]
                diff_cur_event[key] = cur_event[key]
            else:
                sub_diff_prev_event, sub_diff_cur_event = diff_event_as_map(
                    prev_event[key], cur_event[key]
                )
                if sub_diff_prev_event is None or sub_diff_cur_event is None:
                    continue
                diff_prev_event[key] = sub_diff_prev_event
                diff_cur_event[key] = sub_diff_cur_event
        elif isinstance(cur_event[key], list):
            if not isinstance(prev_event[key], list):
                diff_prev_event[key] = prev_event[key]
                diff_cur_event[key] = cur_event[key]
            else:
                sub_diff_prev_event, sub_diff_cur_event = diff_event_as_list(
                    prev_event[key], cur_event[key]
                )
                if sub_diff_prev_event is None or sub_diff_cur_event is None:
                    continue
                diff_prev_event[key] = sub_diff_prev_event
                diff_cur_event[key] = sub_diff_cur_event
        else:
            if prev_event[key] != cur_event[key]:
                diff_prev_event[key] = prev_event[key]
                diff_cur_event[key] = cur_event[key]
    for key in pdc_keys:
        diff_prev_event[key] = prev_event[key]
    for key in cdp_keys:
        diff_cur_event[key] = cur_event[key]
    if len(diff_cur_event) == 0 and len(diff_prev_event) == 0:
        return None, None
    return diff_prev_event, diff_cur_event


def canonicalize_value(value: str):
    if match_mask_regex(value):
        return SIEVE_VALUE_MASK
    else:
        return value


def canonicalize_event_as_list(
    event: List, parent_path: str, masked_keys: Set[str], masked_paths: Set[str]
):
    for i in range(len(event)):
        current_path = os.path.join(parent_path, "*")
        if current_path in masked_paths:
            event[i] = SIEVE_VALUE_MASK
            continue
        if isinstance(event[i], list):
            canonicalize_event_as_list(
                event[i], current_path, masked_keys, masked_paths
            )
        elif isinstance(event[i], dict):
            canonicalize_event_as_map(event[i], current_path, masked_keys, masked_paths)
        elif isinstance(event[i], str):
            event[i] = canonicalize_value(event[i])


def canonicalize_event_as_map(
    event: Dict, parent_path: str, masked_keys: Set[str], masked_paths: Set[str]
):
    for key in event:
        current_path = os.path.join(parent_path, key)
        if key in masked_keys or current_path in masked_paths:
            event[key] = SIEVE_VALUE_MASK
            continue
        if isinstance(event[key], dict):
            canonicalize_event_as_map(
                event[key], current_path, masked_keys, masked_paths
            )
        elif isinstance(event[key], list):
            canonicalize_event_as_list(
                event[key], current_path, masked_keys, masked_paths
            )
        elif isinstance(event[key], str):
            event[key] = canonicalize_value(event[key])


def canonicalize_event(event: Dict, masked_keys: Set[str], masked_paths: Set[str]):
    canonicalize_event_as_map(event, "", masked_keys, masked_paths)


def diff_event(
    prev_event: Dict,
    cur_event: Dict,
    masked_keys: Set[str],
    masked_paths: Set[str],
    trim_ka=False,
    can=True,
) -> Tuple[Optional[Dict], Optional[Dict]]:
    prev_event_copy = copy.deepcopy(prev_event)
    cur_event_copy = copy.deepcopy(cur_event)
    if trim_ka:
        trim_kind_apiversion(prev_event_copy)
        trim_kind_apiversion(cur_event_copy)
    if can:
        canonicalize_event(prev_event_copy, masked_keys, masked_paths)
        canonicalize_event(cur_event_copy, masked_keys, masked_paths)
    diff_prev_event, diff_cur_event = diff_event_as_map(prev_event_copy, cur_event_copy)
    return diff_prev_event, diff_cur_event


def part_of_event_as_list(small_event: List, large_event: List) -> bool:
    if len(small_event) != len(large_event):
        return False
    for i in range(len(small_event)):
        small_val = small_event[i]
        large_val = large_event[i]
        if small_val == SIEVE_IDX_SKIP:
            continue
        if isinstance(small_val, dict):
            if isinstance(large_val, dict):
                if not part_of_event_as_map(small_val, large_val):
                    return False
            else:
                return False
        elif isinstance(small_val, list):
            if isinstance(large_val, list):
                if not part_of_event_as_list(small_val, large_val):
                    return False
            else:
                return False
        else:
            if small_val != large_val:
                return False
    return True


def part_of_event_as_map(small_event: Dict, large_event: Dict) -> bool:
    for key in small_event:
        if key not in large_event:
            return False
    for key in small_event:
        small_val = small_event[key]
        large_val = large_event[key]
        if isinstance(small_val, dict):
            if isinstance(large_val, dict):
                if not part_of_event_as_map(small_val, large_val):
                    return False
            else:
                return False
        elif isinstance(small_val, list):
            if isinstance(large_val, list):
                if not part_of_event_as_list(small_val, large_val):
                    return False
            else:
                return False
        else:
            if small_val != large_val:
                return False
    return True


def conflicting_event_payload(
    small_event: Optional[Dict],
    large_event: Dict,
    masked_keys: Set[str],
    masked_paths: Set[str],
) -> bool:
    if small_event is None:
        return False
    large_event_copy = copy.deepcopy(large_event)
    canonicalize_event(large_event_copy, masked_keys, masked_paths)
    return not part_of_event_as_map(small_event, large_event_copy)


def same_key(prev_event: Dict, cur_event: Dict) -> bool:
    diff_keys = set(prev_event.keys()).symmetric_difference(set(cur_event.keys()))
    if not len(diff_keys) == 0:
        return False
    common_keys = set(prev_event.keys()).intersection(set(cur_event.keys()))
    for key in common_keys:
        if isinstance(prev_event[key], dict):
            if not isinstance(cur_event[key], dict):
                return False
            if not same_key(prev_event[key], cur_event[key]):
                return False
    return True


def trim_kind_apiversion(event: Dict):
    event.pop("kind", None)
    event.pop("apiVersion", None)
