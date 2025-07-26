# 狼人杀游戏 (Werewolf Game)

一个基于 FastAPI 和 DashScope 的 AI 驱动狼人杀游戏。

## 项目简介

本项目是一个完整的狼人杀游戏实现，包含后端 API 和前端界面。游戏中除了预言家、守卫和普通村民外，狼人也由 AI 扮演，玩家可以作为观察者观看游戏进程。

游戏使用 DashScope 提供的通义千问大模型来驱动 AI 玩家的行为和发言，创造一个完全由 AI 参与的狼人杀游戏体验。

## 功能特点

- 完整的狼人杀游戏逻辑实现（夜晚行动、投票、角色技能等）
- AI 扮演狼人、预言家、守卫和村民角色
- WebSocket 实时通信，支持多人同时观战
- 基于 FastAPI 构建的高性能后端 API
- 响应式前端界面，实时显示游戏状态
- 支持多种游戏角色：
  - 狼人 (Wolf)
  - 预言家 (Seer)
  - 守卫 (Guard)
  - 村民 (Villager)

## 技术栈

- 后端：Python, FastAPI, WebSocket
- 前端：HTML, CSS, JavaScript
- AI：DashScope, 通义千问大模型
- 部署：支持 Vercel 部署

## 环境要求

- Python 3.8+
- DashScope API Key

## 安装步骤

1. 克隆项目：
   ```bash
   git clone <repository-url>
   cd FastAPIProject
   ```

2. 安装依赖：
   ```bash
   pip install -r requirements.txt
   ```

3. 配置环境变量：
   ```bash
   cp .env.example .env
   ```
   在 `.env` 文件中填入你的 DashScope API Key：
   ```
   DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```

4. 运行项目：
   ```bash
   python main.py
   ```

## 使用方法

1. 启动服务后，访问 `http://localhost:8000/static/index.html` 进入游戏界面
2. 点击"创建游戏"开始新游戏
3. 游戏会自动进行，AI 玩家将根据游戏状态进行发言和行动
4. 你可以作为观察者观看游戏全过程

## API 接口

- `POST /games/` - 创建新游戏
- `GET /games/{game_id}` - 获取游戏状态
- `POST /games/{game_id}/players/{player_id}/action` - 玩家执行操作
- `GET /games/{game_id}/players/{player_id}/role` - 获取玩家角色信息
- `GET /games/{game_id}/logs` - 获取游戏日志
- WebSocket `ws://localhost:8000/ws/{game_id}/{player_id}` - 实时通信连接

## 目录结构

```
.
├── main.py              # 主应用文件
├── config.py            # 配置文件
├── requirements.txt     # 依赖列表
├── .env.example         # 环境变量示例
├── logic/               # 游戏逻辑代码
│   ├── gamemanager.py   # 游戏管理器
│   ├── game_utils.py    # 游戏工具函数
│   ├── player.py        # 玩家类
│   └── model_config.py  # AI模型配置
├── static/              # 静态文件
│   └── index.html       # 前端界面
└── README.md
```

## 部署

### 本地部署

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

### Vercel 部署

项目支持 Vercel 部署，配置文件见 `vercel.json`。

## 许可证

MIT License