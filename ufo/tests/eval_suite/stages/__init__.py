# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Stages package for UFO Evaluation Suite."""

from tests.eval_suite.stages.stage_r1 import (
    DEFAULT_FILENAME as STAGE_R1_DEFAULT_FILENAME,
    DEFAULT_MESSAGE as STAGE_R1_DEFAULT_MESSAGE,
    DEFAULT_REQUEST as STAGE_R1_DEFAULT_REQUEST,
    pre_cleanup as pre_cleanup_r1,
    verify_r1,
)
from tests.eval_suite.stages.stage_r2 import (
    DEFAULT_INITIAL_URL as STAGE_R2_DEFAULT_INITIAL_URL,
    DEFAULT_REQUEST as STAGE_R2_DEFAULT_REQUEST,
    DEFAULT_SECOND_URL as STAGE_R2_DEFAULT_SECOND_URL,
    pre_cleanup as pre_cleanup_r2,
    verify_r2,
)
from tests.eval_suite.stages.stage_r3 import (
    DEFAULT_REQUEST as STAGE_R3_DEFAULT_REQUEST,
    pre_cleanup as pre_cleanup_r3,
    verify_r3,
)
from tests.eval_suite.stages.stage_r4 import (
    DEFAULT_REPORT_FILENAME as STAGE_R4_DEFAULT_REPORT_FILENAME,
    DEFAULT_REQUEST as STAGE_R4_DEFAULT_REQUEST,
    pre_cleanup as pre_cleanup_r4,
    verify_r4,
)
from tests.eval_suite.stages.stage_r5 import (
    DEFAULT_REQUEST as STAGE_R5_DEFAULT_REQUEST,
    DEFAULT_SUMMARY_FILENAME as STAGE_R5_DEFAULT_SUMMARY_FILENAME,
    pre_cleanup as pre_cleanup_r5,
    verify_r5,
)

__all__ = [
    "verify_r1",
    "pre_cleanup_r1",
    "STAGE_R1_DEFAULT_FILENAME",
    "STAGE_R1_DEFAULT_MESSAGE",
    "STAGE_R1_DEFAULT_REQUEST",
    "verify_r2",
    "pre_cleanup_r2",
    "STAGE_R2_DEFAULT_INITIAL_URL",
    "STAGE_R2_DEFAULT_SECOND_URL",
    "STAGE_R2_DEFAULT_REQUEST",
    "verify_r3",
    "pre_cleanup_r3",
    "STAGE_R3_DEFAULT_REQUEST",
    "verify_r4",
    "pre_cleanup_r4",
    "STAGE_R4_DEFAULT_REPORT_FILENAME",
    "STAGE_R4_DEFAULT_REQUEST",
    "verify_r5",
    "pre_cleanup_r5",
    "STAGE_R5_DEFAULT_SUMMARY_FILENAME",
    "STAGE_R5_DEFAULT_REQUEST",
]
