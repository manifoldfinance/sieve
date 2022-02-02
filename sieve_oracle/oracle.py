import os
from sieve_common.common import *
from sieve_oracle.checker_common import *
from sieve_oracle.safety_checker import *
from sieve_oracle.liveness_checker import *


def persist_history(test_context: TestContext):
    cprint("Generating state update summary...", bcolors.OKGREEN)
    history = generate_history(test_context)
    history_digest = generate_history_digest(test_context)
    dump_json_file(test_context.result_dir, history, "history.json")
    dump_json_file(test_context.result_dir, history_digest, "event.json")


def persist_state(test_context: TestContext):
    cprint("Generating end state...", bcolors.OKGREEN)
    state = generate_state(test_context)
    dump_json_file(test_context.result_dir, state, "state.json")


def canonicalize_history_and_state(test_context: TestContext):
    assert test_context.mode == sieve_modes.LEARN_TWICE
    cprint("Generating canonicalized state update summary...", bcolors.OKGREEN)
    can_history_digest = canonicalize_history_digest(test_context)
    dump_json_file(test_context.oracle_dir, can_history_digest, "event.json")
    cprint("Generating canonicalized end state...", bcolors.OKGREEN)
    can_state = canonicalize_state(test_context)
    dump_json_file(test_context.oracle_dir, can_state, "state.json")
    cprint(
        "Generating canonicalized state mask (for generating test plans)...",
        bcolors.OKGREEN,
    )
    state_mask = generate_state_mask(can_state)
    dump_json_file(test_context.oracle_dir, state_mask, "mask.json")
    cprint("Generating controller family list...", bcolors.OKGREEN)
    controller_related_list = generate_controller_related_list(test_context)
    dump_json_file(
        test_context.oracle_dir, controller_related_list, "controller_family.json"
    )


def operator_panic_checker(test_context: TestContext):
    operator_log = os.path.join(test_context.result_dir, "streamed-operator.log")
    ret_val = 0
    messages = []
    file = open(operator_log)
    for line in file.readlines():
        if "Observed a panic" in line:
            panic_in_file = line[line.find("Observed a panic") :]
            messages.append(
                generate_alarm("Exception from controller:", panic_in_file.strip())
            )
            ret_val += 1
    messages.sort()
    return ret_val, messages


def test_failure_checker(test_context: TestContext):
    workload_log = os.path.join(test_context.result_dir, "workload.log")
    ret_val = 0
    messages = []
    file = open(workload_log)
    for line in file.readlines():
        if line.startswith("error:"):
            ret_val += 1
            messages.append(generate_alarm("Error from the workload:", line.strip()))
    messages.sort()
    return ret_val, messages


def textbook_checker(test_context: TestContext):
    ret_val = 0
    messages = []
    if test_context.common_config.controller_exception_check_enabled:
        panic_ret_val, panic_messages = operator_panic_checker(test_context)
        ret_val += panic_ret_val
        messages.extend(panic_messages)

    if test_context.common_config.workload_error_check_enabled:
        workload_ret_val, workload_messages = test_failure_checker(test_context)
        ret_val += workload_ret_val
        messages.extend(workload_messages)
    return ret_val, messages


def safety_checker(test_context: TestContext):
    ret_val = 0
    messages = []
    if test_context.common_config.state_update_summary_check_enabled:
        if not test_context.mode == sieve_modes.UNOBSR_STATE:
            (
                compare_history_digests_ret_val,
                compare_history_digests_messages,
            ) = compare_history_digests(test_context)
            ret_val += compare_history_digests_ret_val
            messages.extend(compare_history_digests_messages)
    return ret_val, messages


def liveness_checker(test_context: TestContext):
    ret_val = 0
    messages = []
    if test_context.common_config.end_state_check_enabled:
        if not (
            test_context.mode == sieve_modes.STALE_STATE and test_context.use_csi_driver
        ):
            compare_states_ret_val, compare_states_messages = compare_states(
                test_context
            )
            ret_val += compare_states_ret_val
            messages.extend(compare_states_messages)
    return ret_val, messages


def check(test_context: TestContext):
    ret_val = 0
    messages = []

    validation_ret_val, validation_messages = injection_validation(test_context)
    if validation_ret_val < 0:
        messages.extend(validation_messages)

    textbook_ret_val, textbook_messages = textbook_checker(test_context)
    ret_val += textbook_ret_val
    messages.extend(textbook_messages)

    safety_ret_val, safety_messages = safety_checker(test_context)
    ret_val += safety_ret_val
    messages.extend(safety_messages)

    liveness_ret_val, liveness_messages = liveness_checker(test_context)
    ret_val += liveness_ret_val
    messages.extend(liveness_messages)

    if validation_ret_val < 0:
        ret_val = validation_ret_val

    return ret_val, "\n".join(messages)
