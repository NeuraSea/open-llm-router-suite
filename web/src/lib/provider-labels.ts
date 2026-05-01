export function formatProviderLabel(provider: string) {
  switch (provider) {
    case "claude-max":
      return "Claude Max OAuth";
    case "openai-codex":
      return "OpenAI Codex OAuth";
    case "openai":
      return "OpenAI API";
    case "anthropic":
      return "Anthropic";
    case "zhipu":
      return "ZhipuAI (智谱)";
    case "deepseek":
      return "DeepSeek";
    case "qwen":
      return "Qwen (通义千问)";
    case "minimax":
      return "MiniMax";
    case "jina":
      return "Jina AI";
    case "anthropic_compat":
      return "Anthropic 兼容";
    case "openai_compat":
      return "OpenAI 兼容";
    default:
      return provider;
  }
}

export function modelGroupKey(provider: string, providerAlias?: string | null) {
  return providerAlias || provider;
}

export function formatModelGroupLabel(provider: string, providerAlias?: string | null) {
  return providerAlias || formatProviderLabel(provider);
}
