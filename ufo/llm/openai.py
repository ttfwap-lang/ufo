import asyncio
import functools
import json
import logging
import os
import shutil
import sys
from typing import Any, Callable, Dict, List, Literal, Optional
import httpx
import openai
from openai import AzureOpenAI, OpenAI
from ufo.llm import AgentType
from ufo.llm.base import BaseService
from ufo.llm.endpoint import is_local_endpoint
from ufo.llm.llm_result import LLMResult
from ufo.llm.response_schema import AppAgentResponse, EvaluationResponse, HostAgentResponse

def _pydantic_to_response_format(schema_class):
    """
    Convert a Pydantic model class to an OpenAI response_format parameter.
    Uses public Pydantic API instead of private OpenAI SDK internals.

    :param schema_class: A Pydantic BaseModel subclass
    :return: A dict suitable for the response_format parameter
    """
    return {'type': 'json_schema', 'json_schema': {'name': schema_class.__name__, 'schema': schema_class.model_json_schema(), 'strict': True}}
logger = logging.getLogger(__name__)
_PROBED_JSON_SCHEMA_MODELS: Dict[str, bool] = {}

class BaseOpenAIService(BaseService):

    def __init__(self, config: Dict[str, Any], agent_type: str, api_provider: str, api_base: str) -> None:
        """
        Create an OpenAI service instance.
        :param config: The configuration for the OpenAI service.
        :param agent_type: The type of the agent.
        :param api_provider: The type of the API provider (e.g., "openai", "aoai", "azure_ad").
        :param api_base: The base URL of the API.
        """
        self.config_llm = config[agent_type]
        self.config = config
        self.api_type = self.config_llm['API_TYPE'].lower()
        self.max_retry = self.config['MAX_RETRY']
        self.prices = self.config.get('PRICES', {})
        self.agent_type = agent_type
        self.json_schema_enabled = False
        self.logger = logging.getLogger(__name__)
        assert api_provider in ['openai', 'aoai', 'azure_ad'], 'Invalid API Provider'
        self.use_responses = bool(self.config_llm.get('USE_RESPONSES', False))
        self.client: OpenAI = OpenAIService.get_openai_client(api_provider, api_base, self.max_retry, self.config['TIMEOUT'], self.config_llm.get('API_KEY', ''), self.config_llm.get('API_VERSION', ''), aad_api_scope_base=self.config_llm.get('AAD_API_SCOPE_BASE', ''), aad_tenant_id=self.config_llm.get('AAD_TENANT_ID', ''), use_responses=self.use_responses)
        self.model = self.config_llm['API_MODEL']
        self.api_provider = api_provider
        self.api_base = api_base
        self.probe_key = f'{api_provider}:{api_base}:{self.model}'
        if self.probe_key in _PROBED_JSON_SCHEMA_MODELS:
            self.json_schema_enabled = _PROBED_JSON_SCHEMA_MODELS[self.probe_key]
            self.config_llm['JSON_SCHEMA'] = self.json_schema_enabled
        else:
            self.json_schema_enabled = bool(self.config_llm.get('JSON_SCHEMA', False))

    async def _ensure_json_schema_probed(self) -> None:
        """Probe JSON schema support lazily and offload to thread."""
        if self.use_responses:
            return
        if self.probe_key in _PROBED_JSON_SCHEMA_MODELS:
            self.json_schema_enabled = _PROBED_JSON_SCHEMA_MODELS[self.probe_key]
            self.config_llm['JSON_SCHEMA'] = self.json_schema_enabled
            return
        is_local_proxy = is_local_endpoint(api_base=self.api_base, api_key=self.config_llm.get('API_KEY'), api_type=self.api_provider)
        if is_local_proxy:
            self.json_schema_enabled = bool(self.config_llm.get('JSON_SCHEMA', False))
            _PROBED_JSON_SCHEMA_MODELS[self.probe_key] = self.json_schema_enabled
            return

        def _sync_probe() -> bool:
            try:
                self.client.chat.completions.create(model=self.model, messages=[{'role': 'user', 'content': 'Hello'}], n=1, response_format=_pydantic_to_response_format(HostAgentResponse), max_tokens=10)
                _PROBED_JSON_SCHEMA_MODELS[self.probe_key] = True
                return True
            except openai.BadRequestError as e:
                if "'response_format' of type 'json_schema' is not supported" in getattr(e, 'message', str(e)):
                    self.logger.info(f'Model {self.model} does not support Structured JSON Output feature. Switching to text mode.')
                _PROBED_JSON_SCHEMA_MODELS[self.probe_key] = False
                return False
            except Exception as e:
                self.logger.warning(f'Startup probe for model {self.model} failed with {type(e).__name__}: {e}. Continuing without JSON schema validation.')
                _PROBED_JSON_SCHEMA_MODELS[self.probe_key] = False
                return False
        self.json_schema_enabled = await asyncio.to_thread(_sync_probe)
        self.config_llm['JSON_SCHEMA'] = self.json_schema_enabled

    async def _chat_completion(self, messages: List[Dict[str, str]], stream: bool=False, temperature: Optional[float]=None, max_tokens: Optional[int]=None, top_p: Optional[float]=None, **kwargs: Any) -> LLMResult:
        """
        Generates completions for a given conversation using the OpenAI Chat API asynchronously.
        :param messages: The list of messages in the conversation.
        :param stream: Whether to stream the API response.
        :param temperature: The temperature parameter for randomness in the output.
        :param max_tokens: The maximum number of tokens in the generated completion.
        :param top_p: The top-p parameter for nucleus sampling.
        :param kwargs: Additional keyword arguments to pass to the OpenAI API.
        :return: LLMResult containing responses, cost, token counts, and metadata.
        """
        temperature = temperature if temperature is not None else self.config['TEMPERATURE']
        max_tokens = max_tokens if max_tokens is not None else self.config['MAX_TOKENS']
        top_p = top_p if top_p is not None else self.config['TOP_P']
        if self.use_responses:
            return await self._responses_completion(messages=messages, temperature=temperature, max_tokens=max_tokens, top_p=top_p)
        await self._ensure_json_schema_probed()
        base_params = {'model': self.model, 'messages': messages, 'n': 1, **kwargs}
        if self.json_schema_enabled:
            response_format_mapping = {AgentType.HOST: HostAgentResponse, AgentType.APP: AppAgentResponse, AgentType.EVALUATION: EvaluationResponse}
            response_format = response_format_mapping.get(AgentType(self.agent_type))
            if response_format:
                base_params['response_format'] = _pydantic_to_response_format(response_format)
        if not self.config_llm.get('REASONING_MODEL', False):
            base_params.update({'temperature': temperature, 'top_p': top_p})
        if stream:
            base_params.update({'stream': True, 'stream_options': {'include_usage': True}})
        response = await asyncio.to_thread(self.client.chat.completions.create, **base_params)
        if stream:
            collected_content = ['']
            prompt_tokens = 0
            completion_tokens = 0
            for chunk in response:
                if chunk.choices:
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        collected_content[0] += delta.content
                else:
                    usage = getattr(chunk, 'usage', None)
                    if usage:
                        prompt_tokens = getattr(usage, 'prompt_tokens', 0) or 0
                        completion_tokens = getattr(usage, 'completion_tokens', 0) or 0
            if not collected_content or not collected_content[0]:
                raise RuntimeError(f"OpenAI API streaming response produced empty content for model '{self.model}'")
            cost = self.get_cost_estimator(self.api_type, self.model, self.prices, prompt_tokens, completion_tokens)
            return LLMResult(responses=collected_content, cost=cost, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, model=self.model, api_type=self.api_type, agent_type=self.agent_type if isinstance(self.agent_type, str) else getattr(self.agent_type, 'value', str(self.agent_type)))
        else:
            usage = getattr(response, 'usage', None)
            prompt_tokens = getattr(usage, 'prompt_tokens', 0) if usage else 0
            completion_tokens = getattr(usage, 'completion_tokens', 0) if usage else 0
            cost = self.get_cost_estimator(self.api_type, self.model, self.prices, prompt_tokens, completion_tokens)
            if not response.choices or response.choices[0].message.content is None:
                raise RuntimeError(f"OpenAI API returned response with no choices or empty content for model '{self.model}'")
            responses = [response.choices[0].message.content]
            return LLMResult(responses=responses, cost=cost, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, model=self.model, api_type=self.api_type, agent_type=self.agent_type if isinstance(self.agent_type, str) else getattr(self.agent_type, 'value', str(self.agent_type)))

    async def _responses_completion(self, messages: List[Dict[str, str]], temperature: Optional[float]=None, max_tokens: Optional[int]=None, top_p: Optional[float]=None) -> LLMResult:
        """
        Generate a completion using the Responses API asynchronously.
        """
        inputs = self._messages_to_responses_input(messages)
        base_params: Dict[str, Any] = {'model': self.model, 'input': inputs}
        if not self.config_llm.get('REASONING_MODEL', False):
            base_params.update({'temperature': temperature, 'top_p': top_p})
        if max_tokens is not None:
            base_params['max_output_tokens'] = max_tokens
        if self.json_schema_enabled:
            response_format_mapping = {AgentType.HOST: HostAgentResponse, AgentType.APP: AppAgentResponse, AgentType.EVALUATION: EvaluationResponse}
            response_format = response_format_mapping.get(AgentType(self.agent_type))
            if response_format:
                base_params['response_format'] = _pydantic_to_response_format(response_format)
        try:
            response = await asyncio.to_thread(self.client.responses.create, **base_params)
        except openai.BadRequestError as e:
            if 'response_format' in str(e).lower():
                base_params.pop('response_format', None)
                response = await asyncio.to_thread(self.client.responses.create, **base_params)
            else:
                raise
        response_dict = response.model_dump() if hasattr(response, 'model_dump') else response
        content_text = self._extract_responses_text(response_dict)
        usage = response_dict.get('usage', {}) if isinstance(response_dict, dict) else {}
        input_tokens = usage.get('input_tokens', 0) if isinstance(usage, dict) else 0
        output_tokens = usage.get('output_tokens', 0) if isinstance(usage, dict) else 0
        cost = self.get_cost_estimator(self.api_type, self.model, self.prices, input_tokens, output_tokens)
        return LLMResult(responses=[content_text], cost=cost, prompt_tokens=input_tokens, completion_tokens=output_tokens, model=self.model, api_type=self.api_type, agent_type=self.agent_type if isinstance(self.agent_type, str) else getattr(self.agent_type, 'value', str(self.agent_type)))

    @staticmethod
    def _messages_to_responses_input(messages: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        """
        Convert chat-style messages to Responses API input format.
        """
        inputs: List[Dict[str, Any]] = []
        for msg in messages:
            role = msg.get('role', 'user')
            content = msg.get('content', '')
            if isinstance(content, list):
                converted_parts: List[Dict[str, Any]] = []
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    part_type = part.get('type')
                    if part_type == 'text':
                        converted_parts.append({'type': 'input_text', 'text': part.get('text', '')})
                    elif part_type in ['image_url', 'input_image']:
                        image_url = part.get('image_url', '')
                        if isinstance(image_url, dict):
                            image_url = image_url.get('url', '')
                        converted_parts.append({'type': 'input_image', 'image_url': image_url})
                    else:
                        converted_parts.append(part)
                inputs.append({'role': role, 'content': converted_parts})
            else:
                inputs.append({'role': role, 'content': [{'type': 'input_text', 'text': str(content)}]})
        return inputs

    @staticmethod
    def _extract_responses_text(response: Dict[str, Any]) -> str:
        """
        Extract text content from a Responses API payload.
        """
        output = response.get('output', [])
        chunks: List[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get('content', [])
            for part in content:
                if not isinstance(part, dict):
                    continue
                if 'text' in part:
                    chunks.append(part.get('text', ''))
                elif part.get('type') in ['output_text', 'text']:
                    chunks.append(part.get('text', ''))
        return ''.join(chunks).strip()

    async def _chat_completion_operator(self, message: Dict[str, Any]={}, **kwargs: Any) -> LLMResult:
        """
        Generates completions for a given conversation using the OpenAI Operator / Responses API.
        :param message: The message to send to the API.
        :return: LLMResult containing the response dict in responses[0], cost, tokens, and metadata.
        """
        inputs = message.get('inputs', [])
        tools = message.get('tools', [])
        previous_response_id = message.get('previous_response_id', None)
        create_params = {'model': self.config_llm.get('API_MODEL'), 'input': inputs, 'tools': tools, 'previous_response_id': previous_response_id, 'truncation': 'auto', 'temperature': self.config.get('TEMPERATURE', 0), 'top_p': self.config.get('TOP_P', 0), 'timeout': self.config.get('TIMEOUT', 20)}
        raw_response = await asyncio.to_thread(self.client.responses.create, **create_params)
        response = raw_response.model_dump() if hasattr(raw_response, 'model_dump') else raw_response
        if isinstance(response, dict) and 'usage' in response:
            usage = response.get('usage', {})
            input_tokens = usage.get('input_tokens', 0) if isinstance(usage, dict) else 0
            output_tokens = usage.get('output_tokens', 0) if isinstance(usage, dict) else 0
        else:
            input_tokens = 0
            output_tokens = 0
        cost = self.get_cost_estimator(self.api_type, self.config_llm['API_MODEL'], self.prices, input_tokens, output_tokens)
        return LLMResult(responses=[response], cost=cost, prompt_tokens=input_tokens, completion_tokens=output_tokens, model=self.config_llm.get('API_MODEL', 'gpt-4o'), api_type=self.api_type, agent_type=self.agent_type if isinstance(self.agent_type, str) else getattr(self.agent_type, 'value', str(self.agent_type)))

    @functools.lru_cache()
    @staticmethod
    def get_openai_client(api_type: str, api_base: str, max_retry: int, timeout: int, api_key: Optional[str]=None, api_version: Optional[str]=None, aad_api_scope_base: Optional[str]=None, aad_tenant_id: Optional[str]=None, use_responses: bool=False) -> OpenAI:
        """
        Create an OpenAI client based on the API type.
        :param api_type: The type of the API, one of "openai", "aoai", or "azure_ad".
        :param api_base: The base URL of the API.
        :param max_retry: The maximum number of retries for the API request.
        :param timeout: The timeout for the API request.
        :param api_key: The API key for the OpenAI API.
        :param api_version: The API version for the Azure OpenAI API.
        :param aad_api_scope_base: The AAD API scope base for the Azure OpenAI API.
        :param aad_tenant_id: The AAD tenant ID for the Azure OpenAI API.
        :return: The OpenAI client.
        """
        http_client = httpx.Client(limits=httpx.Limits(max_keepalive_connections=200, max_connections=400), timeout=timeout)
        if api_type == 'openai':
            assert api_key, 'OpenAI API key must be specified'
            assert api_base, 'OpenAI API base URL must be specified'
            client = OpenAI(base_url=api_base, api_key=api_key, max_retries=0, timeout=timeout, http_client=http_client)
        else:
            assert api_version, 'Azure OpenAI API version must be specified'
            if api_type == 'aoai':
                assert api_key, 'Azure OpenAI API key must be specified'
                client = AzureOpenAI(max_retries=0, timeout=timeout, api_version=api_version, azure_endpoint=api_base, api_key=api_key, default_headers={'x-ms-enable-preview': 'true'} if use_responses else {}, http_client=http_client)
            else:
                assert aad_api_scope_base and aad_tenant_id, 'AAD API scope base and tenant ID must be specified'
                token_provider = OpenAIService.get_aad_token_provider(aad_api_scope_base=aad_api_scope_base, aad_tenant_id=aad_tenant_id)
                client = AzureOpenAI(max_retries=0, timeout=timeout, api_version=api_version, azure_endpoint=api_base, azure_ad_token_provider=token_provider, default_headers={'x-ms-enable-preview': 'true'} if use_responses else {}, http_client=http_client)
        return client

    @functools.lru_cache()
    @staticmethod
    def get_aad_token_provider(aad_api_scope_base: str, aad_tenant_id: str, token_cache_file: str='aoai-token-cache.bin', client_id: Optional[str]=None, client_secret: Optional[str]=None, use_azure_cli: Optional[bool]=None, use_broker_login: Optional[bool]=None, use_managed_identity: Optional[bool]=None, use_device_code: Optional[bool]=None, **kwargs) -> Callable[[], str]:
        """
        Acquire token from Azure AD for OpenAI.
        :param aad_api_scope_base: The base scope for the Azure AD API.
        :param aad_tenant_id: The tenant ID for the Azure AD API.
        :param token_cache_file: The path to the token cache file.
        :param client_id: The client ID for the AAD app.
        :param client_secret: The client secret for the AAD app.
        :param use_azure_cli: Use Azure CLI for authentication.
        :param use_broker_login: Use broker login for authentication.
        :param use_managed_identity: Use managed identity for authentication.
        :param use_device_code: Use device code for authentication.
        :return: The access token for OpenAI.
        """
        import msal
        from azure.identity import AuthenticationRecord, AzureCliCredential, ClientSecretCredential, DeviceCodeCredential, ManagedIdentityCredential, TokenCachePersistenceOptions, get_bearer_token_provider
        from azure.identity.broker import InteractiveBrowserBrokerCredential
        api_scope_base = 'api://' + aad_api_scope_base
        tenant_id = aad_tenant_id
        scope = api_scope_base + '/.default'
        token_cache_option = TokenCachePersistenceOptions(name=token_cache_file, enable_persistence=True, allow_unencrypted_storage=True)

        def save_auth_record(auth_record: AuthenticationRecord):
            try:
                with open(token_cache_file, 'w', encoding='utf-8') as cache_file:
                    cache_file.write(auth_record.serialize())
            except Exception as e:
                print('failed to save auth record', e)

        def load_auth_record() -> Optional[AuthenticationRecord]:
            try:
                if not os.path.exists(token_cache_file):
                    return None
                with open(token_cache_file, 'r', encoding='utf-8') as cache_file:
                    return AuthenticationRecord.deserialize(cache_file.read())
            except Exception as e:
                print('failed to load auth record', e)
                return None
        auth_record: Optional[AuthenticationRecord] = load_auth_record()
        current_auth_mode: Literal['client_secret', 'managed_identity', 'az_cli', 'interactive', 'device_code', 'none'] = 'none'
        implicit_mode = not (use_managed_identity or use_azure_cli or use_broker_login or use_device_code)
        if use_managed_identity or (implicit_mode and client_id is not None):
            if not use_managed_identity and client_secret is not None:
                assert client_id is not None, 'client_id must be specified with client_secret'
                current_auth_mode = 'client_secret'
                identity = ClientSecretCredential(client_id=client_id, client_secret=client_secret, tenant_id=tenant_id, cache_persistence_options=token_cache_option, authentication_record=auth_record)
            else:
                current_auth_mode = 'managed_identity'
                if client_id is None:
                    identity = ManagedIdentityCredential(cache_persistence_options=token_cache_option)
                else:
                    identity = ManagedIdentityCredential(client_id=client_id, cache_persistence_options=token_cache_option)
        elif use_azure_cli or (implicit_mode and shutil.which('az') is not None):
            current_auth_mode = 'az_cli'
            identity = AzureCliCredential(tenant_id=tenant_id)
        else:
            if implicit_mode:
                if sys.platform.startswith('darwin') or sys.platform.startswith('win32'):
                    use_broker_login = True
                elif os.environ.get('WSL_DISTRO_NAME', '') != '':
                    use_broker_login = True
                elif os.environ.get('TERM_PROGRAM', '') == 'vscode':
                    use_broker_login = True
                else:
                    use_broker_login = False
            if use_broker_login:
                current_auth_mode = 'interactive'
                identity = InteractiveBrowserBrokerCredential(tenant_id=tenant_id, cache_persistence_options=token_cache_option, use_default_broker_account=True, parent_window_handle=msal.PublicClientApplication.CONSOLE_WINDOW_HANDLE, authentication_record=auth_record)
            else:
                current_auth_mode = 'device_code'
                identity = DeviceCodeCredential(tenant_id=tenant_id, cache_persistence_options=token_cache_option, authentication_record=auth_record)
            try:
                auth_record = identity.authenticate(scopes=[scope])
                if auth_record:
                    save_auth_record(auth_record)
            except Exception as e:
                print(f'failed to acquire token from AAD for OpenAI using {current_auth_mode}', e)
                raise e
        try:
            return get_bearer_token_provider(identity, scope)
        except Exception as e:
            print('failed to acquire token from AAD for OpenAI', e)
            raise e

class OpenAIService(BaseOpenAIService):
    """
    The OpenAI service class to interact with the OpenAI API.
    """

    def __init__(self, config: Dict[str, Any], agent_type: str) -> None:
        """
        Create an OpenAI service instance.
        :param config: The configuration for the OpenAI service.
        :param agent_type: The type of the agent.
        """
        super().__init__(config, agent_type, config[agent_type]['API_TYPE'].lower(), config[agent_type]['API_BASE'])

    async def chat_completion(self, messages: List[Dict[str, str]], n: int=1, stream: bool=False, temperature: Optional[float]=None, max_tokens: Optional[int]=None, top_p: Optional[float]=None, **kwargs: Any) -> LLMResult:
        """
        Generates completions for a given conversation using the OpenAI Chat API asynchronously.
        :param messages: The list of messages in the conversation.
        :param n: The number of completions to generate.
        :param stream: Whether to stream the API response.
        :param temperature: The temperature parameter for randomness in the output.
        :param max_tokens: The maximum number of tokens in the generated completion.
        :param top_p: The top-p parameter for nucleus sampling.
        :param kwargs: Additional keyword arguments to pass to the OpenAI API.
        :return: LLMResult containing responses, cost, token counts, and metadata.
        """
        if self.agent_type.lower() != 'operator':
            return await super()._chat_completion(messages, stream=stream, temperature=temperature, max_tokens=max_tokens, top_p=top_p, **kwargs)
        else:
            return await super()._chat_completion_operator(messages)

class OperatorServicePreview(BaseService):
    """
    The Operator service class for Computer Using Agent (CUA) workflows.
    Uses the Responses API with the 'computer' tool type.
    Note: The legacy 'computer-use-preview' model was retired July 2026.
    For current usage, configure with GPT-5.6 Terra or latest CUA-capable model.
    """

    def __init__(self, config: Dict[str, Any], agent_type: str='operator', client=None) -> None:
        """
        Create an Operator service instance.
        :param config: The configuration for the Operator service.
        :param agent_type: The type of the agent.

        """
        self.config_llm = config[agent_type]
        self.config = config
        self.api_type = self.config_llm['API_TYPE'].lower()
        self.api_model = self.config_llm['API_MODEL'].lower()
        self.max_retry = self.config['MAX_RETRY']
        self.prices = self.config.get('PRICES', {})
        self._agent_type = agent_type
        if client is None:
            self.client = self.get_openai_client()

    def get_openai_client(self):
        """
        Create an OpenAI client based on the API type.
        :return: The OpenAI client.
        """
        token_provider = self.get_token_provider()
        api_key = token_provider()
        client = openai.AzureOpenAI(azure_endpoint=self.config_llm.get('API_BASE'), api_key=api_key, max_retries=0, timeout=self.config.get('TIMEOUT', 20), api_version=self.config_llm.get('API_VERSION'), default_headers={'x-ms-enable-preview': 'true'})
        return client

    async def chat_completion(self, message: Dict[str, Any]=None, n: int=1) -> LLMResult:
        """
        Generates completions for a given conversation using the OpenAI Responses API asynchronously.
        :param message: The message to send to the API.
        :param n: The number of completions to generate.
        :return: LLMResult containing the response dict in responses[0], cost, tokens, and metadata.
        """
        message = message or {}
        inputs = message.get('inputs', [])
        tools = message.get('tools', [])
        previous_response_id = message.get('previous_response_id', None)
        create_params = {'model': self.config_llm.get('API_MODEL'), 'input': inputs, 'tools': tools, 'previous_response_id': previous_response_id, 'truncation': 'auto', 'temperature': self.config.get('TEMPERATURE', 0), 'top_p': self.config.get('TOP_P', 0), 'timeout': self.config.get('TIMEOUT', 20)}
        raw_response = await asyncio.to_thread(self.client.responses.create, **create_params)
        response = raw_response.model_dump() if hasattr(raw_response, 'model_dump') else raw_response
        if isinstance(response, dict) and 'usage' in response:
            usage = response.get('usage', {})
            input_tokens = usage.get('input_tokens', 0) if isinstance(usage, dict) else 0
            output_tokens = usage.get('output_tokens', 0) if isinstance(usage, dict) else 0
        else:
            input_tokens = 0
            output_tokens = 0
        cost = self.get_cost_estimator(self.api_type, self.api_model, self.prices, input_tokens, output_tokens)
        return LLMResult(responses=[response], cost=cost, prompt_tokens=input_tokens, completion_tokens=output_tokens, model=self.api_model, api_type=self.api_type, agent_type=self._agent_type if isinstance(self._agent_type, str) else getattr(self._agent_type, 'value', str(self._agent_type)))

    def get_token_provider(self):
        """
        Acquire token from Azure AD for OpenAI.
        :return: The access token for OpenAI.
        """
        from azure.identity import AzureCliCredential, get_bearer_token_provider
        tenant_id = self.config_llm.get('AAD_TENANT_ID', '')
        scope = self.config_llm.get('AAD_API_SCOPE', '')
        identity = AzureCliCredential(tenant_id=tenant_id)
        bearer_provider = get_bearer_token_provider(identity, scope)
        return bearer_provider

class OpenAIError(Exception):
    request_id: str
    status_code: int
    message: Dict[str, Any]

    def __init__(self, status_code: int, message: Dict[str, Any], request_id: str):
        """
        The OpenAI API error class.
        :param status_code: The status code of the API response.
        :param message: The error message from the API response.
        :param request_id: The request ID of the API response.
        """
        self.status_code = status_code
        self.message = message
        self.request_id = request_id
        super().__init__(f'OpenAI API error: {status_code} {message}')

    def __str__(self):
        return f'OpenAI API error: {self.request_id} {self.status_code} {json.dumps(self.message, indent=2)}'