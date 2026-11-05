const assert = (condition, message) => {
  if (!condition) throw new Error(message);
};

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function main() {
  const tabs = await (await fetch("http://127.0.0.1:9222/json/list")).json();
  const tab = tabs.find((item) => item.type === "page" && item.url === "http://127.0.0.1:8765/");
  assert(tab, "Open the local weather page in a Chrome session with remote debugging on port 9222.");

  const socket = new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });

  let nextId = 0;
  const pending = new Map();
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      pending.get(message.id)(message);
      pending.delete(message.id);
    }
  });
  const call = (method, params = {}) => new Promise((resolve) => {
    const id = ++nextId;
    pending.set(id, resolve);
    socket.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async (expression) => {
    const response = await call("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (response.result.exceptionDetails) throw new Error(response.result.exceptionDetails.text);
    return response.result.result.value;
  };
  const clickRegion = async (name) => evaluate(`(() => {
    const button = Array.from(document.querySelectorAll(".region-option"))
      .find((item) => item.innerText.includes(${JSON.stringify(name)}));
    if (!button) return false;
    button.click();
    return true;
  })()`);

  try {
    await call("Page.enable");
    await call("Page.reload", { ignoreCache: true });
    await sleep(400);

    const initial = await evaluate(`({
      city: document.querySelector("#cityInput").value,
      empty: document.querySelector("#weather").innerText,
      weatherRequests: performance.getEntriesByType("resource").filter((item) => item.name.includes("/api/weather")).length,
      historyRows: document.querySelectorAll(".history-row").length,
      historyTotal: Number((document.querySelector("#historyCount").innerText.match(/[0-9]+/) || [0])[0])
    })`);
    assert(!initial.city, "The initial page must have no selected city.");
    assert(initial.empty.includes("选择地区，查看天气") && !initial.empty.includes("选择一个地区") && initial.weatherRequests === 0,
      "The initial page should have one clear region-selection prompt and wait for an explicit choice.");
    assert(initial.historyRows <= 8, "The initial history must be paginated.");

    await evaluate(`(() => {
      window.__mockFailure = false;
      window.__delayedWeatherCity = "";
      window.__resolveDelayedWeather = null;
      window.__weatherCalls = 0;
      window.__realFetch = window.fetch;
      window.fetch = (url, ...args) => {
        if (String(url).includes("/api/weather")) {
          window.__weatherCalls += 1;
          const city = new URL(String(url), location.href).searchParams.get("city");
          if (city === window.__delayedWeatherCity) {
            return new Promise((resolve) => { window.__resolveDelayedWeather = () => resolve(new Response(JSON.stringify({ error: "迟到响应" }), { status: 502 })); });
          }
          if (window.__mockFailure) return Promise.resolve(new Response(JSON.stringify({ error: "模拟失败" }), { status: 502 }));
          const daily = {
            time: ["2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06", "2026-11-07"],
            weather_code: [0, 1, 2, 3, 61],
            temperature_2m_max: [18, 19, 20, 21, 17],
            temperature_2m_min: [8, 9, 10, 11, 7],
            precipitation_probability_max: [0, 10, 20, 30, 40]
          };
          return Promise.resolve(new Response(JSON.stringify({
            place: { name: "朝阳区", country: "中国", latitude: 39.92, longitude: 116.44 },
            current: { time: "2026-11-03T15:00", temperature_2m: 16, apparent_temperature: 15,
              relative_humidity_2m: 45, wind_speed_10m: 4, precipitation: 0, weather_code: 0, is_day: 1 },
            daily, timezone: "Asia/Shanghai"
          }), { headers: { "Content-Type": "application/json" } }));
        }
        return window.__realFetch(url, ...args);
      };
    })()`);

    await evaluate(`document.querySelector("#emptyChoose").click()`);
    await sleep(80);
    const chooserHandoff = await evaluate(`({ focused: document.activeElement.id,
      pickerVisible: !document.querySelector("#regionPicker").hidden,
      expanded: document.querySelector("#cityInput").getAttribute("aria-expanded") })`);
    assert(chooserHandoff.focused === "cityInput" && chooserHandoff.pickerVisible && chooserHandoff.expanded === "true",
      "The empty-state action should focus the search box and open the region picker.");
    assert(await clickRegion("北京市"), "Province option should respond to click.");
    await sleep(60);
    assert(await clickRegion("市辖区"), "City option should respond to click.");
    await sleep(60);
    const breadcrumbReturn = await evaluate(`(() => {
      const province = Array.from(document.querySelectorAll("#regionTrail button.trail-button"))
        .find((item) => item.innerText === "北京市");
      if (!province) return { clicked: false };
      province.click();
      return {
        clicked: true,
        pickerVisible: !document.querySelector("#regionPicker").hidden,
        trail: document.querySelector("#regionTrail").innerText,
        options: Array.from(document.querySelectorAll(".region-option")).map((item) => item.innerText)
      };
    })()`);
    assert(breadcrumbReturn.clicked && breadcrumbReturn.pickerVisible
      && breadcrumbReturn.trail.includes("北京市") && breadcrumbReturn.options.some((item) => item.includes("市辖区")),
      "Breadcrumb navigation should keep the picker open and show the selected upper level's choices.");
    assert(await clickRegion("市辖区"), "City should remain selectable after breadcrumb navigation.");
    await sleep(60);
    assert(await clickRegion("朝阳区"), "County option should respond to click.");

    const loaded = await evaluate(`({
      place: document.querySelector(".place")?.innerText,
      days: document.querySelectorAll(".day").length,
      path: document.querySelector("#cityInput").value
    })`);
    assert(loaded.place === "朝阳区 · 中国" && loaded.days === 5, "County selection should render current weather and a five-day forecast.");
    assert(loaded.path.includes("北京市"), "Successful selection should retain the complete administrative path.");

    const rollback = await evaluate(`(async () => {
      window.__mockFailure = true;
      const ok = await loadWeather("错误城市");
      window.__mockFailure = false;
      return { ok, place: document.querySelector(".place").innerText,
        path: document.querySelector("#cityInput").value, notice: document.querySelector("#notice").innerText };
    })()`);
    assert(!rollback.ok && rollback.place === loaded.place && rollback.path === loaded.path && rollback.notice === "模拟失败",
      "A failed query should retain the previous successful weather and selection.");

    const concurrentRollback = await evaluate(`(async () => {
      window.__delayedWeatherCity = "慢查询";
      const staleRequest = loadWeather("慢查询");
      await Promise.resolve();
      window.__mockFailure = true;
      const latestOk = await loadWeather("最新失败查询");
      const restored = { place: document.querySelector(".place").innerText,
        path: document.querySelector("#cityInput").value };
      window.__resolveDelayedWeather();
      const staleOk = await staleRequest;
      window.__mockFailure = false;
      window.__delayedWeatherCity = "";
      return { latestOk, staleOk, ...restored, finalPlace: document.querySelector(".place").innerText };
    })()`);
    assert(!concurrentRollback.latestOk && !concurrentRollback.staleOk
      && concurrentRollback.place === loaded.place && concurrentRollback.finalPlace === loaded.place
      && concurrentRollback.path === loaded.path,
      "A stale response must not replace the latest visible weather.");

    await evaluate(`(() => {
      const input = document.querySelector("#historyFilter");
      input.value = "";
      input.dispatchEvent(new Event("input", { bubbles: true }));
    })()`);
    let firstPage;
    for (let attempt = 0; attempt < 30; attempt += 1) {
      await sleep(100);
      firstPage = await evaluate(`({ rows: document.querySelectorAll(".history-row").length,
        total: Number((document.querySelector("#historyCount").innerText.match(/[0-9]+/) || [0])[0]),
        moreHidden: document.querySelector("#historyMore").hidden })`);
      if (firstPage.total === initial.historyTotal && firstPage.rows === Math.min(8, firstPage.total)) break;
    }
    assert(firstPage.total === initial.historyTotal && firstPage.rows === Math.min(8, firstPage.total),
      `History should show the first page of up to eight rows: ${JSON.stringify(firstPage)}`);
    assert(firstPage.moreHidden === (firstPage.total <= 8), "Load-more visibility should match whether another page exists.");
    let nextPage = firstPage.rows;
    if (firstPage.total > 8) {
      await evaluate(`document.querySelector("#historyMore").click()`);
      await sleep(180);
      nextPage = await evaluate(`document.querySelectorAll(".history-row").length`);
      assert(nextPage === Math.min(16, firstPage.total), "Load more should append the next history page.");
    }

    for (const viewport of [{ width: 390, height: 844 }, { width: 320, height: 740 }]) {
      await call("Emulation.setDeviceMetricsOverride", { ...viewport, deviceScaleFactor: 1, mobile: true });
      await call("Page.reload", { ignoreCache: true });
      await sleep(250);
      await evaluate(`document.querySelector("#cityInput").focus()`);
      await sleep(80);
      const layout = await evaluate(`(() => {
        const picker = document.querySelector("#regionPicker").getBoundingClientRect();
        return { viewport: innerWidth, document: document.documentElement.scrollWidth,
          pickerLeft: picker.left, pickerRight: picker.right, pickerWidth: picker.width,
          pickerVisible: !document.querySelector("#regionPicker").hidden };
      })()`);
      assert(layout.document <= layout.viewport, `Horizontal page overflow at ${viewport.width}px: ${JSON.stringify(layout)}`);
      assert(layout.pickerVisible && layout.pickerLeft >= 0 && layout.pickerRight <= layout.viewport,
        `Region picker should fit the ${viewport.width}px viewport: ${JSON.stringify(layout)}`);
    }
    await call("Emulation.clearDeviceMetricsOverride");
    await call("Page.reload", { ignoreCache: true });

    console.log(JSON.stringify({ initial, chooserHandoff, breadcrumbReturn, loaded, rollback, concurrentRollback, firstPage, nextPage, responsive: "390px and 320px passed" }));
  } finally {
    socket.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
