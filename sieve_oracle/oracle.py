import copy
import kubernetes
from sieve_common.k8s_event import (
    APIEventTypes,
    SIEVE_API_EVENT_MARK,
    parse_api_event,
    extract_generate_name,
    is_generated_random_name,
    operator_related_resource,
    api_key_to_rtype_namespace_name,
)
import yaml
import json
import os
from sieve_common.common import *
from sieve_common.default_config import sieve_config
import deepdiff
from deepdiff import DeepDiff
from sieve_oracle.checker_common import *
from sieve_oracle.safety_checker import *


api_event_empty_entry = {
    APIEventTypes.ADDED: 0,
    APIEventTypes.DELETED: 0,
}


def generate_test_oracle(project, src_dir, dest_dir, canonicalize_resource=False):
    if sieve_config["generic_event_generation_enabled"]:
        events_oracle = generate_events_oracle(project, src_dir, canonicalize_resource)
        dump_json_file(src_dir, events_oracle, "event.json")
        if canonicalize_resource:
            dump_json_file(dest_dir, events_oracle, "event.json")
    if sieve_config["generic_state_generation_enabled"]:
        resources = generate_resources(src_dir, canonicalize_resource)
        ignore_paths = generate_ignore_paths(resources)
        # we generate state.json at src_dir (log dir)
        dump_json_file(src_dir, resources, "state.json")
        dump_json_file(src_dir, ignore_paths, "mask.json")
        # we generate state.json at dest_dir (data dir) if cononicalize_resource=True
        if canonicalize_resource:
            dump_json_file(dest_dir, resources, "state.json")
            dump_json_file(dest_dir, ignore_paths, "mask.json")


def generate_events_oracle(project, log_dir, canonicalize_resource):
    api_log_path = os.path.join(log_dir, "apiserver1.log")
    api_event_map = {}
    api_key_event_map = {}
    api_type_event_map = {}
    taint_list = []
    for line in open(api_log_path).readlines():
        if SIEVE_API_EVENT_MARK not in line:
            continue
        api_event = parse_api_event(line)
        key = api_event.key
        if (
            api_event.etype != APIEventTypes.ADDED
            and api_event.etype != APIEventTypes.DELETED
        ):
            continue
        if api_event.namespace != "default":
            continue
        generate_name = extract_generate_name(api_event.obj_map)
        if generate_name is not None:
            if is_generated_random_name(api_event.name, generate_name):
                key = key[:-5] + "*"
        assert "/default/" in key
        type_prefix = key[: key.find("/default/")]
        if key not in api_key_event_map:
            api_key_event_map[key] = copy.deepcopy(api_event_empty_entry)
            if operator_related_resource(
                project, api_event.rtype, api_event.name, api_event.obj_map, taint_list
            ):
                api_key_event_map[key]["operator_related"] = True
                taint_list.append((api_event.rtype, api_event.name))
            else:
                api_key_event_map[key]["operator_related"] = False
        api_key_event_map[key][api_event.etype] += 1
        if not is_unstable_api_event_key(key, api_key_event_map[key]):
            if type_prefix not in api_type_event_map:
                api_type_event_map[type_prefix] = copy.deepcopy(api_event_empty_entry)
            api_type_event_map[type_prefix][api_event.etype] += 1

    api_event_map["keys"] = api_key_event_map
    api_event_map["types"] = api_type_event_map

    if canonicalize_resource:
        # Suppose we are current at learn/learn-twice/learn.yaml/xxx
        learn_dir = os.path.dirname(os.path.dirname(log_dir))
        learn_once_dir = os.path.join(learn_dir, "learn-once", "learn.yaml")
        prev_api_event_map = json.loads(
            open(os.path.join(learn_once_dir, "event.json")).read()
        )
        api_event_map = learn_twice_trim(prev_api_event_map, api_event_map)

        def remove_ignored_value(event_map):
            ignored = set()
            for key in event_map:
                if event_map[key] == "SIEVE-IGNORE":
                    ignored.add(key)
                else:
                    for etype in event_map[key]:
                        if event_map[key][etype] == "SIEVE-IGNORE":
                            ignored.add(key)
                            break
            for key in ignored:
                event_map.pop(key, None)

        remove_ignored_value(api_event_map["keys"])
        remove_ignored_value(api_event_map["types"])

    return api_event_map


def get_resource_helper(func):
    k8s_namespace = sieve_config["namespace"]
    response = func(k8s_namespace, _preload_content=False, watch=False)
    data = json.loads(response.data)
    return {resource["metadata"]["name"]: resource for resource in data["items"]}


def get_crd_list():
    data = []
    try:
        for item in json.loads(os.popen("kubectl get crd -o json").read())["items"]:
            data.append(item["spec"]["names"]["singular"])
    except Exception as e:
        print("get_crd_list fail", e)
    return data


def get_crd(crd):
    data = {}
    try:
        for item in json.loads(os.popen("kubectl get {} -o json".format(crd)).read())[
            "items"
        ]:
            data[item["metadata"]["name"]] = item
    except Exception as e:
        print("get_crd fail", e)
    return data


def learn_twice_trim(base_resources, twice_resources):
    def nested_set(dic, keys, value):
        for key in keys[:-1]:
            dic = dic[key]
        dic[keys[-1]] = value

    stored_learn = copy.deepcopy(base_resources)
    ddiff = DeepDiff(twice_resources, base_resources, ignore_order=False, view="tree")

    if "values_changed" in ddiff:
        for key in ddiff["values_changed"]:
            nested_set(stored_learn, key.path(output_format="list"), "SIEVE-IGNORE")

    if "dictionary_item_added" in ddiff:
        for key in ddiff["dictionary_item_added"]:
            nested_set(stored_learn, key.path(output_format="list"), "SIEVE-IGNORE")

    return stored_learn


def generate_resources(log_dir="", canonicalize_resource=False):
    # print("Generating cluster resources digest...")
    kubernetes.config.load_kube_config()
    core_v1 = kubernetes.client.CoreV1Api()
    apps_v1 = kubernetes.client.AppsV1Api()
    # TODO: should we also cover other types?
    resource_handler = {
        "deployment": apps_v1.list_namespaced_deployment,
        # "serviceaccount": core_v1.list_namespaced_service_account,
        # "configmap": core_v1.list_namespaced_config_map,
        "secret": core_v1.list_namespaced_secret,
        "persistentvolumeclaim": core_v1.list_namespaced_persistent_volume_claim,
        "pod": core_v1.list_namespaced_pod,
        "service": core_v1.list_namespaced_service,
        "statefulset": apps_v1.list_namespaced_stateful_set,
    }
    resources = {}

    for resource in resource_handler.keys():
        resources[resource] = get_resource_helper(resource_handler[resource])

    crd_list = get_crd_list()
    # Fetch for crd
    for crd in crd_list:
        resources[crd] = get_crd(crd)

    if canonicalize_resource:
        # Suppose we are current at learn/learn-twice/learn.yaml/xxx
        learn_dir = os.path.dirname(os.path.dirname(log_dir))
        learn_once_dir = os.path.join(learn_dir, "learn-once", "learn.yaml")
        base_resources = json.loads(
            open(os.path.join(learn_once_dir, "state.json")).read()
        )
        resources = learn_twice_trim(base_resources, resources)
    return resources


def dump_ignore_paths(ignore, predefine, key, obj, path):
    if path in predefine["path"] or key in predefine["key"]:
        ignore.add(path)
        return
    if type(obj) is str:
        # Check for SIEVE-IGNORE
        if obj == SIEVE_LEARN_VALUE_MASK:
            ignore.add(path)
            return
        # Check for ignore regex rule
        if match_mask_regex(obj):
            ignore.add(path)
            return
    if type(obj) is list:
        for i in range(len(obj)):
            val = obj[i]
            newpath = os.path.join(path, "*")
            dump_ignore_paths(ignore, predefine, i, val, newpath)
    elif type(obj) is dict:
        for key in obj:
            val = obj[key]
            newpath = os.path.join(path, key)
            dump_ignore_paths(ignore, predefine, key, val, newpath)


def generate_ignore_paths(data):
    result = {}
    for rtype in data:
        result[rtype] = {}
        for name in data[rtype]:
            predefine = {
                "path": set(gen_mask_paths()),
                "key": set(gen_mask_keys()),
            }
            ignore = set()
            if data[rtype][name] != SIEVE_LEARN_VALUE_MASK:
                dump_ignore_paths(ignore, predefine, "", data[rtype][name], "")
                result[rtype][name] = sorted(list(ignore))
    return result


def operator_checker(test_context: TestContext):
    operator_log = os.path.join(test_context.result_dir, "streamed-operator.log")
    ret_val = 0
    messages = []
    file = open(operator_log)
    for line in file.readlines():
        if "Observed a panic" in line:
            panic_in_file = line[line.find("Observed a panic") :]
            messages.append(generate_alarm("[OPERATOR-PANIC]", panic_in_file.strip()))
            ret_val += 1
    messages.sort()
    return ret_val, messages


def test_workload_checker(test_context: TestContext):
    workload_log = os.path.join(test_context.result_dir, "workload.log")
    ret_val = 0
    messages = []
    file = open(workload_log)
    for line in file.readlines():
        if line.startswith("error:"):
            ret_val += 1
            messages.append(generate_alarm("[WORKLOAD]", line.strip()))
    messages.sort()
    return ret_val, messages


def equal_path(template, value):
    template = template.split("/")
    value = value.split("/")

    if len(template) > len(value):
        return False

    for i in range(len(template)):
        if template[i] == "*":
            continue
        if template[i] != value[i]:
            return False
    return True


def preprocess(learn, test):
    for resource in list(learn):
        if resource not in test:
            learn.pop(resource, None)
    for resource in list(test):
        if resource not in learn:
            test.pop(resource, None)


def generic_state_checker(test_context: TestContext):
    learn = json.load(open(os.path.join(test_context.oracle_dir, "state.json")))
    test = json.load(open(os.path.join(test_context.result_dir, "state.json")))

    ret_val = 0
    messages = []

    def nested_get(dic, keys):
        for key in keys:
            dic = dic[key]
        return dic

    preprocess(learn, test)
    tdiff = DeepDiff(learn, test, ignore_order=False, view="tree")
    resource_map = {resource: {"add": [], "remove": []} for resource in test}
    boring_keys = set(gen_mask_keys())
    boring_paths = set(gen_mask_paths())

    for delta_type in tdiff:
        for key in tdiff[delta_type]:
            path = key.path(output_format="list")

            # Handle for resource size diff
            if len(path) == 2:
                resource_type = path[0]
                name = path[1]
                if key.t1 == SIEVE_LEARN_VALUE_MASK:
                    name = SIEVE_LEARN_VALUE_MASK
                resource_map[resource_type][
                    "add" if delta_type == "dictionary_item_added" else "remove"
                ].append(name)
                continue

            if delta_type in ["values_changed", "type_changes"]:
                if (
                    key.t1 == SIEVE_LEARN_VALUE_MASK
                    or match_mask_regex(key.t1)
                    or match_mask_regex(key.t2)
                ):
                    continue

            has_not_care = False
            # Search for boring keys
            for kp in path:
                if kp in boring_keys:
                    has_not_care = True
                    break
            # Search for boring paths
            if len(path) > 2:
                for rule in boring_paths:
                    if equal_path(rule, "/".join([str(x) for x in path[2:]])):
                        has_not_care = True
                        break
            if has_not_care:
                continue

            resource_type = path[0]
            if len(path) == 2 and type(key.t2) is deepdiff.helper.NotPresent:
                source = learn
            else:
                source = test

            name = nested_get(source, path[:2] + ["metadata", "name"])
            namespace = nested_get(source, path[:2] + ["metadata", "namespace"])

            if name == "sieve-testing-global-config":
                continue
            ret_val += 1
            if delta_type in ["dictionary_item_added", "iterable_item_added"]:
                messages.append(
                    generate_alarm(
                        "[RESOURCE-KEY-ADD]",
                        "{} {} {} {} {}".format(
                            "/".join([resource_type, namespace, name]),
                            "/".join(map(str, path[2:])),
                            "not seen during learning run, but seen as",
                            key.t2,
                            "during testing run",
                        ),
                    )
                )
            elif delta_type in ["dictionary_item_removed", "iterable_item_removed"]:
                messages.append(
                    generate_alarm(
                        "[RESOURCE-KEY-REMOVE]",
                        "{} {} {} {} {}".format(
                            "/".join([resource_type, namespace, name]),
                            "/".join(map(str, path[2:])),
                            "seen as",
                            key.t1,
                            "during learning run, but not seen during testing run",
                        ),
                    )
                )
            elif delta_type == "values_changed":
                messages.append(
                    generate_alarm(
                        "[RESOURCE-KEY-DIFF]",
                        "{} {} {} {} {} {} {}".format(
                            "/".join([resource_type, namespace, name]),
                            "/".join(map(str, path[2:])),
                            "is",
                            key.t1,
                            "during learning run, but",
                            key.t2,
                            "during testing run",
                        ),
                    )
                )
            else:
                messages.append(
                    generate_alarm(
                        "[RESOURCE-KEY-UNKNOWN-CHANGE]",
                        "{} {} {} {} {} {} {}".format(
                            delta_type,
                            "/".join([resource_type, namespace, name]),
                            "/".join(map(str, path[2:])),
                            "is",
                            key.t1,
                            " => ",
                            key.t2,
                        ),
                    )
                )

    for resource_type in resource_map:
        resource = resource_map[resource_type]
        if SIEVE_LEARN_VALUE_MASK in resource["add"] + resource["remove"]:
            # Then we only report number diff
            delta = len(resource["add"]) - len(resource["remove"])
            learn_set = set(learn[resource_type].keys())
            test_set = set(test[resource_type].keys())
            if delta != 0:
                ret_val += 1
                messages.append(
                    generate_alarm(
                        "[ALARM][RESOURCE-ADD]"
                        if delta > 0
                        else "[ALARM][RESOURCE-REMOVE]",
                        "{} {} {} {} {} {} {} {} {}".format(
                            len(learn_set),
                            resource_type,
                            "seen after learning run",
                            sorted(learn_set),
                            "but",
                            len(test_set),
                            resource_type,
                            "seen after testing run",
                            sorted(test_set),
                        ),
                    )
                )
        else:
            # We report resource diff detail
            for name in resource["add"]:
                ret_val += 1
                messages.append(
                    generate_alarm(
                        "[ALARM][RESOURCE-ADD]",
                        "{} {}".format(
                            "/".join([resource_type, name]),
                            "is not seen during learning run, but seen during testing run",
                        ),
                    )
                )
            for name in resource["remove"]:
                ret_val += 1
                messages.append(
                    generate_alarm(
                        "[ALARM][RESOURCE-REMOVE]",
                        "{} {}".format(
                            "/".join([resource_type, name]),
                            "is seen during learning run, but not seen during testing run",
                        ),
                    )
                )

    messages.sort()
    return ret_val, messages


def print_error_and_debugging_info(ret_val, messages, test_config):
    if ret_val == 0:
        return
    test_config_content = yaml.safe_load(open(test_config))
    report_color = bcolors.FAIL if ret_val > 0 else bcolors.WARNING
    cprint("[RET VAL] {}\n".format(ret_val) + messages, report_color)
    if sieve_config["injection_desc_generation_enabled"]:
        hint = "[DEBUGGING SUGGESTION]\n" + generate_debugging_hint(test_config_content)
        cprint(hint, bcolors.WARNING)


def safety_checker(test_context: TestContext):
    ret_val = 0
    messages = []
    if (
        sieve_config["generic_event_checker_enabled"]
        and test_context.mode != sieve_modes.OBS_GAP
    ):
        write_ret_val, write_messages = compare_history_digests(test_context)
        ret_val += write_ret_val
        messages.extend(write_messages)
    return ret_val, messages


def check(test_context: TestContext):
    ret_val = 0
    messages = []

    validation_ret_val, validation_messages = injection_validation(test_context)
    if validation_ret_val < 0:
        messages.extend(validation_messages)

    if sieve_config["operator_checker_enabled"]:
        panic_ret_val, panic_messages = operator_checker(test_context)
        ret_val += panic_ret_val
        messages.extend(panic_messages)

    if sieve_config["test_workload_checker_enabled"]:
        workload_ret_val, workload_messages = test_workload_checker(test_context)
        ret_val += workload_ret_val
        messages.extend(workload_messages)

    # if sieve_config["generic_event_checker_enabled"]:
    write_ret_val, write_messages = safety_checker(test_context)
    ret_val += write_ret_val
    messages.extend(write_messages)

    if sieve_config["generic_state_checker_enabled"]:
        resource_ret_val, resource_messages = generic_state_checker(test_context)
        ret_val += resource_ret_val
        messages.extend(resource_messages)

    if validation_ret_val < 0:
        ret_val = validation_ret_val

    return ret_val, "\n".join(messages)
