#!/usr/bin/env bash
set -euo pipefail

MODEL="llama3.2:1b"
API="http://localhost:11434/api/generate"
DIR="$(cd "$(dirname "$0")" && pwd)/results"

mkdir -p "$DIR"

# 동일한 조건으로 비교하기 위한 요청
PAYLOAD=$(jq -n --arg model "$MODEL" '{
  model: $model,
  prompt: "Explain Kubernetes readiness probes in three sentences.",
  stream: false,
  keep_alive: "10m",
  options: {
    temperature: 0,
    seed: 42,
    num_predict: 128
  }
}')

# 기존에 로드된 모델 언로드
curl -fsS "$API" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"$MODEL\",\"keep_alive\":0}" \
  > /dev/null

# 첫 요청 = Cold, 두 번째 요청 = Warm
for phase in cold warm; do
  echo "Running $phase benchmark..."

  curl -fsS "$API" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD" > "$DIR/$phase.json"

  jq -e '.done == true and
         .total_duration > 0 and
         .eval_duration > 0' \
    "$DIR/$phase.json" > /dev/null

  jq -r --arg phase "$phase" '{
    phase: $phase,
    total_ms: (.total_duration / 1000000),
    load_ms: (.load_duration / 1000000),
    output_tokens: .eval_count,
    tokens_per_sec: (
      .eval_count * 1000000000 / .eval_duration
    )
  }' "$DIR/$phase.json"
done
