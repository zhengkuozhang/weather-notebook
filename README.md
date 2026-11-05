<div align="center">

# 🌦️ 天气记录本

**风雨有时 · 记录有痕**

一款在本机运行的天气查询与观测记录工具，让每一次查询都有迹可循。

![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white)
![SQLite](https://img.shields.io/badge/Storage-SQLite-003B57?logo=sqlite&logoColor=white)
![Dependencies](https://img.shields.io/badge/Python依赖-仅标准库-176B52)
![Status](https://img.shields.io/badge/运行方式-本地服务-176B52)

[项目简介](#项目简介) · [快速开始](#快速开始) · [使用指南](#使用指南) · [开发与测试](#开发与测试) · [数据与许可](#数据与许可)

</div>

---

## 项目简介

天气记录本将当前天气、未来五天预报和本机历史记录放在同一个页面中。后端通过 Open-Meteo 获取天气，通过地理编码服务定位城市；每次成功查询都会把当前天气快照写入本地 SQLite 数据库。

项目采用 Python 标准库和原生 HTML / CSS / JavaScript，无需安装第三方 Python 包，也无需申请 API Key。页面使用纸张色背景、深绿色观测区域和中文字体，兼顾桌面与窄屏浏览。

> **记录方式：** 首次打开不预设城市，也不会自动查询天气。只有主动选择地区或提交查询，才会获取天气并保存快照。

## 功能亮点

- **中国行政区逐级选择**：内置 34 个省级地区、3,361 个县级及同级条目，支持省 → 市 / 区域 → 县 / 区选择。
- **全球城市搜索**：同时展示本地行政区匹配与全球城市结果，使用地区和国家信息区分同名城市。
- **坐标定位查询**：全球搜索结果按所选坐标查询；中国县区按完整行政路径定位，并缓存坐标。
- **天气与预报**：展示温度、体感温度、湿度、风速、降水和未来五天最高 / 最低温及降水概率。
- **本机采集记录**：查询成功后保存当前天气快照，区分当地观测时间与本机采集时间。
- **历史浏览与趋势**：按城市筛选，每次加载 8 条记录，并绘制当前返回记录的温度趋势。
- **CSV 导出**：导出全部天气记录，包含 UTF-8 BOM，便于 Excel / Numbers 打开。
- **记录清理**：删除前显示确认对话框；清理天气记录后保留地理编码缓存。

## 技术实现

```text
浏览器：原生 HTML / CSS / JavaScript
                  │ 同源 HTTP
Python ThreadingHTTPServer
    ├── Open-Meteo：城市搜索、当前天气、五天预报
    ├── Nominatim：中国行政区边界定位
    ├── regions.json：离线行政区列表
    └── SQLite：天气快照、坐标缓存
```

页面没有前端构建步骤。服务默认仅监听 `127.0.0.1`，数据保存在项目目录内。

## 快速开始

### 环境要求

- Python **3.9 或更新版本**。
- 现代浏览器。
- 可访问 Open-Meteo 和 OpenStreetMap Nominatim 的网络。
- 双击启动脚本适用于 macOS；其他系统可从终端启动。

### 启动服务

在本项目目录中执行：

```bash
python3 server.py
```

打开 **<http://127.0.0.1:8765>**。

macOS 也可以双击 `start.command`。若文件缺少执行权限，可先执行：

```bash
chmod +x start.command
```

在运行服务的终端按 `Ctrl+C` 停止。

> **端口提示：** 同目录下的「观澜 · 股票研究台」也默认使用 `8765`。同时运行时，请修改本项目 `server.py` 顶部的 `PORT` 后再启动；浏览器回归脚本中的地址也需要同步调整。

## 使用指南

### 查询天气

1. 点击“选择地区，查看天气”或城市输入框。
2. 逐级选择中国行政区，或者输入城市名称并选择搜索结果。
3. 查看当前天气和未来五天预报。
4. 查询成功后，右侧历史记录会更新，并按当前城市筛选。

全球同名城市应从搜索结果中选择，以便使用精确坐标。直接提交文本时，后端会采用 Open-Meteo 返回的首个城市结果。

### 浏览与导出记录

- 在历史筛选框中输入完整城市名，查看该城市记录；筛选采用名称精确匹配。
- 使用“加载更多记录”或滚动至列表底部继续浏览。
- 点击刷新按钮重新读取本机历史，不会主动重新采集天气。
- 点击“导出”，确认后下载**全部记录**，不受当前城市筛选限制。
- 点击删除按钮并确认后，删除全部天气记录。该操作无法撤销，建议先导出。

温度趋势使用本次接口返回的记录绘制；加载其他分页时会更新曲线，并非完整历史统计。

## HTTP 接口

- `GET /`：天气查询页面。
- `GET /api/regions`：内置行政区列表。
- `GET /api/locations?q=Paris`：全球城市搜索，少于两个字符时返回空列表。
- `GET /api/weather?city=Shanghai`：查询天气，并在成功后保存当前天气快照。
- `GET /api/weather?city=Paris&latitude=48.8534&longitude=2.3488&country=France`：使用指定坐标查询。
- `GET /api/weather?city=朝阳区&path=北京市|市辖区|朝阳区`：按行政路径定位查询；实际调用时需编码参数。
- `GET /api/history?city=Shanghai&limit=8&offset=0`：历史分页，`limit` 最大为 `100`。
- `GET /api/export`：下载全部天气记录 CSV。
- `DELETE /api/history`：删除全部天气观测记录。

> `GET /api/weather` 会产生数据库写入。批量调用前请确认采集意图，并遵守上游服务的使用限制。

## 目录结构

```text
.
├── README.md           # 项目说明
├── server.py           # HTTP 服务、天气查询、定位与 SQLite 存储
├── index.html          # 页面结构、样式和交互逻辑
├── regions.json        # 内置中国行政区数据
├── build_regions.py    # 行政区数据更新脚本
├── start.command       # macOS 启动入口
├── test_server.py      # Python 单元及 HTTP 测试
├── test_browser.js     # Chrome 浏览器交互回归
└── weather_history.db  # 本地运行数据库，不应提交
```

`.pycache/`、`__pycache__/` 和 `.pyc` 为运行缓存，不属于业务源码。

## 本地数据与备份

数据库包含：

- `observations`：天气观测快照、城市、坐标、观测时间和采集时间。
- `geocode_cache`：行政路径与坐标缓存，减少重复定位请求。

最简单的完整备份方式是**停止服务后**复制 `weather_history.db` 到其他位置。恢复时先停止服务，再放回备份文件。

删除数据库文件会同时删除天气记录与坐标缓存；下次启动时会重新创建数据库。仅需清空天气记录时，优先使用页面中的删除操作。

## 开发与测试

### Python 测试

在本项目目录执行：

```bash
python3 -m unittest -v
```

测试使用临时数据库和模拟上游响应，覆盖天气写入、精确坐标、行政路径缓存、台湾地区名称匹配、分页、删除、旧数据库迁移及 CSV 公式单元格防护。

### 浏览器回归

`test_browser.js` 通过 Chrome DevTools Protocol 连接已打开的浏览器，需要支持全局 `fetch` 和 `WebSocket` 的 Node.js 版本。

1. 启动本地天气服务。
2. 启动开启远程调试的 Chrome，并打开 `http://127.0.0.1:8765/`。
3. 在项目目录执行 `node test_browser.js`。

macOS 启动示例：

```bash
open -na "Google Chrome" --args \
  --remote-debugging-port=9222 \
  --user-data-dir=/tmp/weather-notebook-chrome \
  http://127.0.0.1:8765/

node test_browser.js
```

该脚本覆盖地区选择、查询失败、迟到响应、历史分页及 390px / 320px 布局。它会读取并操作当前测试页面，建议使用独立浏览器配置目录。

### 更新行政区数据

```bash
python3 build_regions.py
```

脚本联网读取来源数据并覆盖 `regions.json`。更新后应重新运行测试，核对地区数量与选择器行为。

## 常见问题

<details>
<summary><strong>启动时报 Address already in use</strong></summary>

`8765` 端口已被其他程序占用。停止占用服务，或修改 `server.py` 中的 `PORT`。同时运行股票研究台时也需要分配不同端口。

</details>

<details>
<summary><strong>行政区列表可选，但查询失败</strong></summary>

行政区列表来自本地文件，实际坐标和天气仍依赖网络。检查 Nominatim / Open-Meteo 的可达性；部分县区暂时没有符合条件的行政边界结果，可尝试其他地区或全球城市搜索。

</details>

<details>
<summary><strong>为什么没有自动采集？</strong></summary>

当前实现按用户查询保存快照，没有定时采集任务。刷新历史只读取已有数据库，不会调用天气服务。

</details>

## 数据与许可

- 天气与全球城市搜索：[Open-Meteo](https://open-meteo.com/)。当前天气是其最新模型 / 观测数据，不保证等同于本地传感器实时读数。
- 行政区数据：[modood/Administrative-divisions-of-China](https://github.com/modood/Administrative-divisions-of-China)，来源项目声明 WTFPL。
- 中国行政区定位：[OpenStreetMap Nominatim](https://nominatim.openstreetmap.org/)，使用时遵守其[服务使用政策](https://operations.osmfoundation.org/policies/nominatim/)。代码对定位请求限制间隔并缓存结果。
- 地图数据：© OpenStreetMap contributors，遵循 ODbL。

上游免费服务的使用范围、商业许可与配额请以各来源最新条款为准。本项目不包含 API Key，也不会绕过登录、验证码或访问限制。

**项目许可证：** 当前目录未提供 `LICENSE` 文件；第三方数据的许可不等于本项目代码的许可。
