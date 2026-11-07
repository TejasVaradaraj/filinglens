
import anthropic

from filinglens import config

# Prices in dollars per 1 million tokens (Claude Haiku 5.5, prompts under 100K tokens).
INPUT_PRICE_PER_M = 0.10
OUTPUT_PRICE_PER_M = 0.50

config.require_anthropic_key()
client = anthropic.Anthropic()

response = client.messages.create(
    model=config.MODEL,
    max_tokens=16000,
    system="You are a financial analyst. Answer in 2-3 sentences.",
    output_config={"effort": config.DEFAULT_EFFORT},
    messages=[{"role": "user", "content": "What is a 10-K, and why do investors read it?"}],
)

for block in response.content:
    if block.type == "text":
        print(block.text)

usage = response.usage
cost = (usage.input_tokens / 1_000_000 * INPUT_PRICE_PER_M
        + usage.output_tokens / 1_000_000 * OUTPUT_PRICE_PER_M)
print("\n--- usage ---")
print(f"input tokens:  {usage.input_tokens}")
print(f"output tokens: {usage.output_tokens}")
print(f"cost:          ${cost:.6f}")
print(f"stop reason:   {response.stop_reason}")