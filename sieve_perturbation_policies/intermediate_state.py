import json
import os
from typing import List
from sieve_common.event_delta import *
from sieve_common.common import *
from sieve_common.k8s_event import *
from sieve_analyzer.causality_graph import (
    CausalityGraph,
    CausalityVertex,
)
from sieve_perturbation_policies.common import (
    nondeterministic_key,
    detectable_event_diff,
)


def intermediate_state_detectable_pass(
    test_context: TestContext, causality_vertices: List[CausalityVertex]
):
    print("Running intermediate state detectable pass...")
    candidate_vertices = []
    for vertex in causality_vertices:
        if vertex.is_operator_non_k8s_write():
            candidate_vertices.append(vertex)
        else:
            operator_write = vertex.content
            if nondeterministic_key(
                test_context,
                operator_write,
            ):
                continue
            if detectable_event_diff(
                False,
                operator_write.slim_prev_obj_map,
                operator_write.slim_cur_obj_map,
                operator_write.prev_etype,
                operator_write.etype,
                operator_write.signature_counter,
            ):
                candidate_vertices.append(vertex)
    print("%d -> %d writes" % (len(causality_vertices), len(candidate_vertices)))
    return candidate_vertices


def effective_write_filtering_pass(causality_vertices: List[CausalityVertex]):
    print("Running optional pass:  effective-write-filtering...")
    candidate_vertices = []
    for vertex in causality_vertices:
        if vertex.is_operator_non_k8s_write():
            candidate_vertices.append(vertex)
        else:
            if is_creation_or_deletion(vertex.content.etype):
                candidate_vertices.append(vertex)
            else:
                unmasked_prev_object, unmasked_cur_object = diff_event(
                    vertex.content.prev_obj_map,
                    vertex.content.obj_map,
                    None,
                    None,
                    True,
                    False,
                )
                cur_etype = vertex.content.etype
                empty_write = False
                if unmasked_prev_object == unmasked_cur_object and (
                    cur_etype == OperatorWriteTypes.UPDATE
                    or cur_etype == OperatorWriteTypes.PATCH
                    or cur_etype == OperatorWriteTypes.STATUS_UPDATE
                    or cur_etype == OperatorWriteTypes.STATUS_PATCH
                ):
                    empty_write = True
                elif (
                    unmasked_prev_object is not None
                    and "status" not in unmasked_prev_object
                    and unmasked_cur_object is not None
                    and "status" not in unmasked_cur_object
                    and (
                        cur_etype == OperatorWriteTypes.STATUS_UPDATE
                        or cur_etype == OperatorWriteTypes.STATUS_PATCH
                    )
                ):
                    empty_write = True
                if not empty_write:
                    candidate_vertices.append(vertex)
    print("%d -> %d writes" % (len(causality_vertices), len(candidate_vertices)))
    return candidate_vertices


def no_error_write_filtering_pass(causality_vertices: List[CausalityVertex]):
    print("Running optional pass:  no-error-write-filtering...")
    candidate_vertices = []
    for vertex in causality_vertices:
        if vertex.is_operator_non_k8s_write():
            candidate_vertices.append(vertex)
        elif vertex.content.error in ALLOWED_ERROR_TYPE:
            candidate_vertices.append(vertex)
    print("%d -> %d writes" % (len(causality_vertices), len(candidate_vertices)))
    return candidate_vertices


def generate_intermediate_state_test_plan(
    test_context: TestContext, operator_write: OperatorWrite
):
    resource_key = generate_key(
        operator_write.rtype, operator_write.namespace, operator_write.name
    )
    condition = {}
    if operator_write.etype == OperatorWriteTypes.CREATE:
        condition["conditionType"] = "onObjectCreate"
        condition["resourceKey"] = resource_key
        condition["occurrence"] = operator_write.signature_counter
    elif operator_write.etype == OperatorWriteTypes.DELETE:
        condition["conditionType"] = "onObjectDelete"
        condition["resourceKey"] = resource_key
        condition["occurrence"] = operator_write.signature_counter
    else:
        condition["conditionType"] = "onObjectUpdate"
        condition["resourceKey"] = resource_key
        condition["prevStateDiff"] = json.dumps(
            operator_write.slim_prev_obj_map, sort_keys=True
        )
        condition["curStateDiff"] = json.dumps(
            operator_write.slim_cur_obj_map, sort_keys=True
        )
        condition["occurrence"] = operator_write.signature_counter
    return {
        "actions": [
            {
                "actionType": "restartController",
                "controllerLabel": test_context.controller_config.controller_pod_label,
                "trigger": {
                    "definitions": [
                        {
                            "triggerName": "trigger1",
                            "condition": condition,
                            "observationPoint": {
                                "when": "afterControllerWrite",
                                "by": operator_write.reconciler_type,
                            },
                        }
                    ],
                    "expression": "trigger1",
                },
            }
        ]
    }


def intermediate_state_analysis(
    causality_graph: CausalityGraph, path: str, test_context: TestContext
):
    candidate_vertices = (
        causality_graph.operator_write_vertices
        + causality_graph.operator_non_k8s_write_vertices
    )
    baseline_spec_number = len(candidate_vertices)
    after_p1_spec_number = -1
    after_p2_spec_number = -1
    final_spec_number = -1
    after_p1_spec_number = len(candidate_vertices)
    if test_context.common_config.effective_updates_pruning_enabled:
        candidate_vertices = effective_write_filtering_pass(candidate_vertices)
        candidate_vertices = no_error_write_filtering_pass(candidate_vertices)
        after_p2_spec_number = len(candidate_vertices)
    if test_context.common_config.nondeterministic_pruning_enabled:
        candidate_vertices = intermediate_state_detectable_pass(
            test_context, candidate_vertices
        )
    final_spec_number = len(candidate_vertices)
    i = 0
    for vertex in candidate_vertices:
        operator_write = vertex.content

        if isinstance(operator_write, OperatorWrite):
            intermediate_state_test_plan = generate_intermediate_state_test_plan(
                test_context, operator_write
            )
            i += 1
            file_name = os.path.join(
                path, "intermediate-state-test-plan-%s.yaml" % (str(i))
            )
            if test_context.common_config.persist_test_plans_enabled:
                dump_to_yaml(intermediate_state_test_plan, file_name)
        else:
            print("skip nk write for now")
            # assert isinstance(operator_write, OperatorNonK8sWrite)
            # # TODO: We need a better handling for non k8s event
            # intermediate_state_config["se-name"] = operator_write.fun_name
            # intermediate_state_config["se-namespace"] = "default"
            # intermediate_state_config["se-rtype"] = operator_write.recv_type
            # intermediate_state_config[
            #     "se-reconciler-type"
            # ] = operator_write.reconciler_type
            # intermediate_state_config["se-etype-previous"] = ""
            # intermediate_state_config["se-etype-current"] = NON_K8S_WRITE
            # intermediate_state_config["se-diff-previous"] = json.dumps({})
            # intermediate_state_config["se-diff-current"] = json.dumps({})
            # intermediate_state_config["se-counter"] = str(
            #     operator_write.signature_counter
            # )

    cprint(
        "Generated %d intermediate-state test plan(s) in %s" % (i, path),
        bcolors.OKGREEN,
    )
    return (
        baseline_spec_number,
        after_p1_spec_number,
        after_p2_spec_number,
        final_spec_number,
    )
