import os
import yaml
import re
import json
import glob
from sieve_common.default_config import CommonConfig, ControllerConfig

NO_ERROR_MESSAGE = ""

POD = "pod"
PVC = "persistentvolumeclaim"
DEPLOYMENT = "deployment"
STS = "statefulset"
SECRET = "secret"
SERVICE = "service"

PENDING = "Pending"
RUNNING = "Running"
TERMINATED = "Terminated"
BOUND = "Bound"

SIEVE_IDX_SKIP = "SIEVE-SKIP"
SIEVE_VALUE_MASK = "SIEVE-NON-NIL"
SIEVE_LEARN_VALUE_MASK = "SIEVE-IGNORE"

EXIST = True
NONEXIST = False

METADATA_FIELDS = [
    "name",
    "generateName",
    "namespace",
    "selfLink",
    "uid",
    "resourceVersion",
    "generation",
    "creationTimestamp",
    "deletionTimestamp",
    "deletionGracePeriodSeconds",
    "labels",
    "annotations",
    "ownerReferences",
    "finalizers",
    "clusterName",
    "managedFields",
]


TIME_REG = "^[0-9]+-[0-9]+-[0-9]+T[0-9]+:[0-9]+:[0-9]+Z$"
IP_REG = "^((25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$"

MASK_REGS = [TIME_REG, IP_REG]


class sieve_stages:
    LEARN = "learn"
    TEST = "test"


class sieve_modes:
    TEST = "test"
    VANILLA = "vanilla"
    LEARN_ONCE = "learn-once"
    LEARN_TWICE = "learn-twice"
    ALL = "all"
    NONE = "none"


class sieve_built_in_test_patterns:
    STALE_STATE = "stale-state"
    UNOBSERVED_STATE = "unobserved-state"
    INTERMEDIATE_STATE = "intermediate-state"


class TestContext:
    def __init__(
        self,
        project,
        test_name,
        stage,
        mode,
        phase,
        test_config,
        result_dir,
        oracle_dir,
        docker_repo,
        docker_tag,
        num_apiservers,
        num_workers,
        use_csi_driver,
        common_config: CommonConfig,
        controller_config: ControllerConfig,
    ):
        self.project = project
        self.test_name = test_name
        self.stage = stage
        self.mode = mode
        self.phase = phase
        self.test_config = test_config
        self.result_dir = result_dir
        self.oracle_dir = oracle_dir
        self.docker_repo = docker_repo
        self.docker_tag = docker_tag
        self.num_apiservers = num_apiservers
        self.num_workers = num_workers
        self.use_csi_driver_for_ref = use_csi_driver
        self.use_csi_driver = use_csi_driver
        self.common_config = common_config
        self.controller_config = controller_config
        self.test_plan = None
        self.action_types = []
        if self.stage == sieve_stages.TEST and self.mode == sieve_modes.TEST:
            self.test_plan = yaml.safe_load(open(test_config))
            if self.test_plan["actions"] is not None:
                for action in self.test_plan["actions"]:
                    self.action_types.append(action["actionType"])
            if "reconnectController" in self.action_types:
                if self.num_apiservers < 3:
                    self.num_apiservers = 3
            if self.num_apiservers > 1:
                # csi driver can only work with one apiserver so it cannot be enabled here
                self.use_csi_driver = False
            elif self.use_csi_driver:
                self.num_apiservers = 1
                self.num_workers = 0


def match_mask_regex(val):
    # Search for ignore regex
    if type(val) is str:
        for reg in MASK_REGS:
            pat = re.compile(reg)
            if pat.match(val):
                return True
    return False


def cmd_early_exit(cmd, early_exit=True):
    return_code = os.WEXITSTATUS(os.system(cmd))
    if return_code != 0 and early_exit:
        fail(cmd)
        # sys.exit(1)
        raise Exception(
            "Failed to execute {} with return code {}".format(cmd, return_code)
        )
    return return_code


def dump_json_file(dir, data, json_file_name):
    json.dump(
        data, open(os.path.join(dir, json_file_name), "w"), indent=4, sort_keys=True
    )


def build_directory(test_context: TestContext):
    return os.path.join(
        test_context.common_config.controller_folder, test_context.project, "build"
    )


def deploy_directory(test_context: TestContext):
    return os.path.join(
        test_context.common_config.controller_folder, test_context.project, "deploy"
    )


def test_directory(test_context: TestContext):
    return os.path.join(
        test_context.common_config.controller_folder, test_context.project, "test"
    )


def oracle_directory(test_context: TestContext):
    return os.path.join(
        test_context.common_config.controller_folder, test_context.project, "oracle"
    )


class bcolors:
    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKCYAN = "\033[96m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"


def warn(message):
    print(bcolors.WARNING + "[WARN] " + message + bcolors.ENDC)


def ok(message):
    print(bcolors.OKGREEN + "[OK] " + message + bcolors.ENDC)


def fail(message):
    print(bcolors.FAIL + "[FAIL] " + message + bcolors.ENDC)


def cprint(message, color):
    print(color + message + bcolors.ENDC)


def get_all_controllers(dir):
    controllers = set()
    configs = glob.glob(os.path.join(dir, "*", "config.json"))
    for config in configs:
        tokens = config.split("/")
        controllers.add(tokens[1])
    return controllers


def dump_to_yaml(file_content, file_name):
    yaml.dump(
        file_content,
        open(
            file_name,
            "w",
        ),
        sort_keys=False,
    )
