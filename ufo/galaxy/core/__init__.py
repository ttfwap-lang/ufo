# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Galaxy Framework Core Package

This package contains the core types, interfaces, and utilities for the Galaxy framework.
"""

from .interfaces import (
    # Constellation interfaces
    IConstellation,
    IConstellationBuilder,
    IConstellationExecutor,
    IConstellationUpdater,
    # Dependency interfaces
    IDependency,
    IDependencyResolver,
    # Device interfaces
    IDevice,
    IDeviceRegistry,
    IDeviceSelector,
    IEventLogger,
    # Monitoring interfaces
    IMetricsCollector,
    # Agent interfaces
    IRequestProcessor,
    IResultProcessor,
    ISession,
    # Session interfaces
    ISessionManager,
    # Task interfaces
    ITask,
    # Execution interfaces
    ITaskExecutor,
    ITaskFactory,
)
from .types import (
    AgentId,
    AsyncErrorCallback,
    AsyncProgressCallback,
    ConfigurationError,
    ConstellationConfiguration,
    ConstellationError,
    ConstellationId,
    ConstellationResult,
    DeviceConfiguration,
    DeviceError,
    DeviceId,
    ErrorCallback,
    # Result types
    ExecutionResult,
    # Exception hierarchy
    GalaxyFrameworkError,
    # Context types
    ProcessingContext,
    ProgressCallback,
    SessionId,
    # Utility types
    Statistics,
    # Configuration types
    TaskConfiguration,
    TaskExecutionError,
    # Type aliases
    TaskId,
    ValidationError,
)

__all__ = [
    # Types
    "TaskId",
    "ConstellationId",
    "DeviceId",
    "SessionId",
    "AgentId",
    "ProgressCallback",
    "AsyncProgressCallback",
    "ErrorCallback",
    "AsyncErrorCallback",
    "ExecutionResult",
    "ConstellationResult",
    "TaskConfiguration",
    "ConstellationConfiguration",
    "DeviceConfiguration",
    "ProcessingContext",
    "Statistics",
    # Exceptions
    "GalaxyFrameworkError",
    "TaskExecutionError",
    "ConstellationError",
    "DeviceError",
    "ConfigurationError",
    "ValidationError",
    # Interfaces
    "ITask",
    "ITaskFactory",
    "IDependency",
    "IDependencyResolver",
    "IConstellation",
    "IConstellationBuilder",
    "ITaskExecutor",
    "IConstellationExecutor",
    "IDevice",
    "IDeviceRegistry",
    "IDeviceSelector",
    "IRequestProcessor",
    "IResultProcessor",
    "IConstellationUpdater",
    "ISessionManager",
    "ISession",
    "IMetricsCollector",
    "IEventLogger",
]
