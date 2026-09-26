# MIDI Sustain Parser API

供钢琴教学软件调用的 MIDI 练习分析服务。提交带毫秒时间戳的
`note_on` / `note_off` / `pedal_down` / `pedal_up` 事件及 `end_ms`，
可使用两个接口：

- `POST /api/v1/parse`：返回每次按键的**发声半开区间 `[on_ms, end_ms)`** 及其结束原因。
- `POST /api/v1/practice/align`：将练习中实际弹下的音符与参考音符做全局序列对齐，
  定位**漏弹、多弹及时值（起拍时间）偏差**。

## 快速启动

单条命令（Docker Compose）：

```bash
docker compose up --build
```

- API 地址： `http://localhost:8000`
- 解析接口： `POST http://localhost:8000/api/v1/parse`
- 练习对齐接口： `POST http://localhost:8000/api/v1/practice/align`
- 交互式文档（Swagger UI）： `http://localhost:8000/docs`
- 健康检查： `GET http://localhost:8000/health`
- 端口： `8000`（宿主机映射见 `docker-compose.yml`，可改 `"<宿主端口>:8000"`）

也可以不用 Compose：

```bash
docker build -t midi-sustain-api . && docker run -p 8000:8000 midi-sustain-api
```

本地开发（不用 Docker）：

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

运行测试：

```bash
pip install pytest httpx
python -m pytest tests/ -q
```

## API

### `POST /api/v1/parse`

请求体：

```json
{
  "end_ms": 4000,
  "events": [
    {"type": "pedal_down", "time_ms": 0},
    {"type": "note_on",  "time_ms": 100, "pitch": 60},
    {"type": "note_off", "time_ms": 800, "pitch": 60},
    {"type": "note_on",  "time_ms": 900, "pitch": 64},
    {"type": "pedal_up", "time_ms": 2000}
  ]
}
```

字段约束：

| 字段 | 约束 |
|---|---|
| `end_ms` | 整数，`>= 0` |
| `events[].type` | `note_on` / `note_off` / `pedal_down` / `pedal_up` |
| `events[].time_ms` | 整数，须在 `0 ~ end_ms` 区间内（含端点） |
| `events[].pitch` | 音符事件必填，整数 `0 ~ 127`；踏板事件可省略 |

响应（`200 OK`）：

```json
{
  "end_ms": 4000,
  "note_count": 2,
  "notes": [
    {"press_index": 0, "event_index": 1, "pitch": 60,
     "on_ms": 100, "release_ms": 800, "end_ms": 2000, "end_reason": "pedal_up"},
    {"press_index": 1, "event_index": 3, "pitch": 64,
     "on_ms": 900, "release_ms": null, "end_ms": 4000, "end_reason": "end_ms"}
  ]
}
```

每个音符的发声区间为**半开区间 `[on_ms, end_ms)`**：`on_ms` 时刻发声，
`end_ms` 时刻起不再发声。`notes` 按按键序号 `press_index`（0 起）排列。

| 响应字段 | 含义 |
|---|---|
| `press_index` | 按键序号：该次 `note_on` 在所有按键中的序号（按处理顺序从 0 计） |
| `event_index` | 对应 `note_on` 在请求 `events` 数组中的下标 |
| `on_ms` | 按下时刻，发声区间起点（含） |
| `release_ms` | 实际松键时刻；若直到 `end_ms` 仍按住则为 `null` |
| `end_ms` | 发声区间终点（不含） |
| `end_reason` | `note_off`（松键结束）/ `pedal_up`（延音至抬踏板）/ `end_ms`（持续到结尾） |

## 解析语义

- 事件按 `(time_ms, 输入序号)` 排序处理：时间相同则先提交的先处理。
- 同音高重复按下各自成为独立音符；`note_off` 释放该音高**最早仍按住**的一次。
- 踏板按下期间松键的音符继续发声（延音）；`pedal_up` 只结束这些延音音符，
  仍按住的键不受影响。
- 重复的踏板状态事件（已踩下再 `pedal_down`、已抬起再 `pedal_up`）不改变状态。
- `end_ms` 关闭所有剩余音符（仍按住的与仍在延音的），结束原因为 `end_ms`。

### `POST /api/v1/practice/align`

把练习录音与参考乐谱对照，定位漏弹、多弹和起拍时间偏差。请求体沿用
`/api/v1/parse` 的 `events` / `end_ms` 格式与校验，另附按时间排列的参考音符
和非负容差：

```json
{
  "end_ms": 4000,
  "tolerance_ms": 100,
  "events": [
    {"type": "note_on",  "time_ms": 95,   "pitch": 60},
    {"type": "note_off", "time_ms": 300,  "pitch": 60},
    {"type": "note_on",  "time_ms": 1230, "pitch": 67},
    {"type": "note_on",  "time_ms": 2500, "pitch": 72}
  ],
  "reference": [
    {"pitch": 60, "time_ms": 100},
    {"pitch": 64, "time_ms": 800},
    {"pitch": 67, "time_ms": 1200}
  ]
}
```

字段约束：

| 字段 | 约束 |
|---|---|
| `end_ms` | 整数，`>= 0` |
| `events` | 与 `/api/v1/parse` 完全相同的事件数组，时间须在 `0 ~ end_ms` |
| `reference` | 参考音符数组，按 `time_ms` 升序排列；每项为 `{pitch, time_ms}` |
| `reference[].pitch` | 整数，`0 ~ 127` |
| `reference[].time_ms` | 整数，须在 `0 ~ end_ms` 区间内（含端点） |
| `tolerance_ms` | 非负整数，配对允许的最大起拍时间差（毫秒，含端点） |

响应（`200 OK`）：

```json
{
  "pairs": [
    {"reference_index": 0, "event_index": 0, "time_delta_ms": -5},
    {"reference_index": 2, "event_index": 2, "time_delta_ms": 30}
  ],
  "missed_reference_indices": [1],
  "extra_event_indices": [3]
}
```

| 响应字段 | 含义 |
|---|---|
| `pairs[]` | 成功配对的音符，按参考序号排列 |
| `pairs[].reference_index` | 配对参考音符在请求 `reference` 数组中的下标 |
| `pairs[].event_index` | 配对音符在请求 `events` 数组中的原事件下标（`note_on`） |
| `pairs[].time_delta_ms` | **有符号**时值偏差：实际弹奏时间 − 参考时间（毫秒）；正数为弹晚，负数为弹早 |
| `missed_reference_indices` | 漏弹的参考音符下标（参考中有、弹奏中无） |
| `extra_event_indices` | 多弹的原事件下标（弹奏的 `note_on` 在参考中无对应） |

对齐语义：

- 仅取 `note_on` 事件（忽略 `note_off` 与踏板事件），按
  `(time_ms, 原事件序号)` 排序；参考音符按 `(time_ms, 原参考序号)` 排序。
- 对两个有序序列做**全局序列对齐**（编辑距离式动态规划），每个位置三种走法：
  - **配对**：仅当音高相同且起拍时间差 `<= tolerance_ms` 时允许，代价为绝对时间差；
  - **漏弹**：参考音符未弹，代价为 `tolerance_ms + 1`；
  - **多弹**：弹奏音符无参考，代价为 `tolerance_ms + 1`。
- 取**总代价最小**的对齐路径；代价相同时依次优先：**配对 > 漏弹 > 多弹**。
- 漏弹/多弹代价取 `tolerance_ms + 1`（大于任何一次合法配对的代价），因此
  容差内可配的音符总会优先配对。

## 错误响应

| 状态码 | 场景 |
|---|---|
| `400` | 事件序列语义错误，如 `note_off` 没有对应仍按住的 `note_on`（响应 `detail` 含具体事件下标）；`/api/v1/practice/align` 沿用同一套事件校验与错误格式 |
| `422` | 请求体校验失败：音高超出 `0~127`、事件或参考音符的 `time_ms` 超出 `0~end_ms`、音符事件缺少 `pitch`、`tolerance_ms` 为负数等 |

示例：

```bash
curl -X POST http://localhost:8000/api/v1/parse \
  -H 'Content-Type: application/json' \
  -d '{"end_ms": 1000, "events": [{"type": "note_off", "time_ms": 5, "pitch": 60}]}'
# => 400 {"detail":"note_off at 5 ms for pitch 60 has no matching held note_on (event index 0)"}
```

对齐接口示例：

```bash
curl -X POST http://localhost:8000/api/v1/practice/align \
  -H 'Content-Type: application/json' \
  -d '{
        "end_ms": 2000,
        "tolerance_ms": 100,
        "events": [
          {"type": "note_on", "time_ms": 95, "pitch": 60},
          {"type": "note_on", "time_ms": 530, "pitch": 64}
        ],
        "reference": [
          {"pitch": 60, "time_ms": 100},
          {"pitch": 64, "time_ms": 500}
        ]
      }'
# => 200 {"pairs":[
#   {"reference_index":0,"event_index":0,"time_delta_ms":-5},
#   {"reference_index":1,"event_index":1,"time_delta_ms":30}
# ],"missed_reference_indices":[],"extra_event_indices":[]}
```

## 项目结构

```
app/
  main.py      # FastAPI 应用与路由（/parse 与 /practice/align）
  models.py    # 请求/响应 Pydantic 模型与校验
  sustain.py   # 延音解析核心逻辑（纯标准库，可单测）
  practice.py  # 练习对齐核心逻辑（全局序列对齐 DP，纯标准库，可单测）
tests/
  test_sustain.py
  test_practice_align.py
Dockerfile
docker-compose.yml
requirements.txt
```
