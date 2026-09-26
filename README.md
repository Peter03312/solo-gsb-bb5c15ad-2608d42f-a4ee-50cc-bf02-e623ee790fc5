# MIDI Sustain Parser API

供钢琴教学软件调用的 MIDI 延音解析服务。提交带毫秒时间戳的
`note_on` / `note_off` / `pedal_down` / `pedal_up` 事件及 `end_ms`，
返回每次按键的**发声半开区间 `[on_ms, end_ms)`** 及其结束原因。

## 快速启动

单条命令（Docker Compose）：

```bash
docker compose up --build
```

- API 地址： `http://localhost:8000`
- 解析接口： `POST http://localhost:8000/api/v1/parse`
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

## 错误响应

| 状态码 | 场景 |
|---|---|
| `400` | 事件序列语义错误，如 `note_off` 没有对应仍按住的 `note_on`（响应 `detail` 含具体事件下标） |
| `422` | 请求体校验失败：音高超出 `0~127`、`time_ms` 超出 `0~end_ms`、音符事件缺少 `pitch` 等 |

示例：

```bash
curl -X POST http://localhost:8000/api/v1/parse \
  -H 'Content-Type: application/json' \
  -d '{"end_ms": 1000, "events": [{"type": "note_off", "time_ms": 5, "pitch": 60}]}'
# => 400 {"detail":"note_off at 5 ms for pitch 60 has no matching held note_on (event index 0)"}
```

## 项目结构

```
app/
  main.py      # FastAPI 应用与路由
  models.py    # 请求/响应 Pydantic 模型与校验
  sustain.py   # 延音解析核心逻辑（纯标准库，可单测）
tests/
  test_sustain.py
Dockerfile
docker-compose.yml
requirements.txt
```
