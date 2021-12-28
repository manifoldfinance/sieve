import json
import os

sieve_config = {
    "docker_repo": "ghcr.io/sieve-project/action",
    "namespace": "default",
    "time_travel_front_runner": "kind-control-plane",
    "time_travel_straggler": "kind-control-plane3",
    "api_event_to_check": ["DELETED", "ADDED"],
    "compress_trivial_reconcile": True,
    "workload_wait_soft_timeout": 100,
    "workload_wait_hard_timeout": 600,
    "generic_event_generation_enabled": True,
    "generic_state_generation_enabled": True,
    "generic_object_event_checker_enabled": True,
    "generic_type_event_checker_enabled": False,
    "generic_state_checker_enabled": True,
    "exception_checker_enabled": True,
    "test_workload_checker_enabled": True,
    "injection_desc_generation_enabled": True,
    "spec_generation_detectable_pass_enabled": True,
    "spec_generation_causal_info_pass_enabled": True,
    "spec_generation_type_specific_pass_enabled": True,
    "time_travel_spec_generation_delete_only": True,
    "time_travel_spec_generation_causality_pass_enabled": True,
    "time_travel_spec_generation_reversed_pass_enabled": True,
    "obs_gap_spec_generation_causality_pass_enabled": True,
    "obs_gap_spec_generation_overwrite_pass_enabled": True,
    "atom_vio_spec_generation_error_free_pass_enabled": True,
    "persist_specs_enabled": True,
    "remove_nondeterministic_key_enabled": True,
}

if os.path.isfile("sieve_config.json"):
    json_config = json.loads(open("sieve_config.json").read())
    for key in json_config:
        sieve_config[key] = json_config[key]
    if not sieve_config["generic_state_generation_enabled"]:
        sieve_config["generic_state_checker_enabled"] = False
