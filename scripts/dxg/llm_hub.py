 1 | # Aider - Multi-Agent Config (architect/editor split)
 2 | # Updated 2026-09-27
 3 | 
 4 | # Multi-agent architecture
 5 | architect: true
 6 | model: anthropic/claude-opus-5-5
 7 | model: openai/featherless-deepseek
 8 | model: openai/gx10-qwen3-42b
 9 | 
10 | # Editor model (local coder on gx10)
11 | editor-model: openai/gx10-qwen3-42b
12 | 
13 | # Planner model (cloud, no Anthropic key needed)
14 | planner: deepseek-v4-pro
15 | 
16 | # Hub configuration
17 | hub_port: 4000
18 | hub_upstreams: 8000 8002 8004 8005 8007
19 | 
20 | # Local models (network-wide via hub)
21 | local_models:
22 |   - deepseek-ai/DeepSeek-V4-Pro
23 |   - openai/featherless-ai/deepseek-v4-pro
24 |   - openai/gx10-qwen3-42b
25 | 
26 | # System settings
27 | swappiness: 1
28 | vm_memory_swap: 12G
29 | 
30 | # Gateway
31 |   # Featherless API Key
32 |   FEATHERLESS_API_KEY: rc_38c953cbec577b127f444d436238d3442551e5355d00ca13a3c5ef82b8a96534
33 | liteLLM_gateway: 127.0.0.1:8000