import fs from "node:fs/promises";
import path from "node:path";
import { Presentation, PresentationFile } from "@oai/artifact-tool";

const W = 1280;
const H = 720;
const C = {
  ink: "#111111",
  muted: "#555555",
  light: "#F0F1F3",
  mid: "#D9DDE3",
  rule: "#AEB4BD",
  accent: "#E85D2A",
  accentLight: "#FFE5DA",
  green: "#2F7D4F",
  greenLight: "#E2F3E9",
  blue: "#246BCE",
  blueLight: "#E6F0FF",
  redLight: "#FFE7E7",
};

const finalPptx = process.env.FINAL_PPTX || path.resolve("outputs/a1-radixcache-visual-guide.pptx");
const previewDir = process.env.PREVIEW_DIR || path.resolve("outputs/a1-radixcache-visual-guide-preview");

function addText(slide, text, x, y, w, h, style = {}) {
  const shape = slide.shapes.add({
    geometry: "textbox",
    position: { left: x, top: y, width: w, height: h },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  shape.text = text;
  shape.text.style = {
    fontSize: style.fontSize ?? 20,
    bold: style.bold ?? false,
    color: style.color ?? C.ink,
    alignment: style.alignment ?? "left",
  };
  return shape;
}

function addTitle(slide, title, subtitle = "") {
  addText(slide, title, 52, 42, 1050, 58, { fontSize: 38, bold: true });
  if (subtitle) {
    addText(slide, subtitle, 54, 104, 980, 34, { fontSize: 18, color: C.muted });
  }
  slide.shapes.add({
    geometry: "rect",
    position: { left: 52, top: 152, width: 1176, height: 1.4 },
    fill: C.rule,
    line: { style: "solid", fill: C.rule, width: 0 },
  });
}

function addFooter(slide, n) {
  addText(slide, `A1 RadixCache 机制图解 · ${n}`, 1040, 672, 190, 24, {
    fontSize: 14,
    color: C.muted,
    alignment: "right",
  });
}

function box(slide, text, x, y, w, h, opts = {}) {
  const geometry = opts.geometry || "roundRect";
  const config = {
    geometry: opts.geometry || "roundRect",
    name: opts.name,
    position: { left: x, top: y, width: w, height: h },
    fill: opts.fill ?? "white",
    line: { style: "solid", fill: opts.line ?? C.rule, width: opts.lineWidth ?? 1.2 },
  };
  if (geometry === "rect" || geometry === "textbox" || geometry === "roundRect") {
    config.borderRadius = opts.radius ?? "rounded-md";
  }
  const shape = slide.shapes.add(config);
  shape.text = text;
  shape.text.style = {
    fontSize: opts.fontSize ?? 19,
    bold: opts.bold ?? false,
    color: opts.color ?? C.ink,
    alignment: opts.align ?? "center",
  };
  return shape;
}

function pill(slide, text, x, y, w, h, opts = {}) {
  return box(slide, text, x, y, w, h, {
    fill: opts.fill ?? C.light,
    line: opts.line ?? "none",
    lineWidth: 0,
    radius: "rounded-full",
    fontSize: opts.fontSize ?? 17,
    bold: opts.bold ?? true,
    color: opts.color ?? C.ink,
  });
}

function arrow(slide, from, to, opts = {}) {
  return slide.shapes.connect(from, to, {
    kind: opts.kind ?? "straight",
    fromSide: opts.fromSide ?? "right",
    toSide: opts.toSide ?? "left",
    line: { style: opts.style ?? "solid", fill: opts.color ?? C.muted, width: opts.width ?? 2 },
    tail: { type: "arrow", width: "med", length: "med" },
  });
}

function note(slide, text, x, y, w, h, opts = {}) {
  const s = box(slide, text, x, y, w, h, {
    fill: opts.fill ?? C.light,
    line: opts.line ?? "none",
    lineWidth: opts.lineWidth ?? 0,
    radius: "rounded-md",
    fontSize: opts.fontSize ?? 18,
    bold: opts.bold ?? false,
    align: opts.align ?? "left",
    color: opts.color ?? C.ink,
  });
  return s;
}

function createDeck() {
  const p = Presentation.create({ slideSize: { width: W, height: H } });

  // 1
  {
    const s = p.slides.add();
    s.background.fill = "white";
    addText(s, "A1 RadixCache\n机制图解", 64, 88, 650, 180, { fontSize: 62, bold: true });
    addText(s, "用图理解 SGLang 前缀缓存、叶子淘汰、lock_ref 与 2Q 接口缺口", 68, 300, 760, 70, { fontSize: 24, color: C.muted });
    const root = box(s, "root", 820, 118, 110, 54, { fill: C.ink, color: "white", bold: true });
    const sys = box(s, "共享前缀", 760, 238, 230, 58, { fill: C.blueLight, line: C.blue, bold: true });
    const a = box(s, "请求 A 尾部", 670, 386, 190, 58, { fill: "white" });
    const b = box(s, "请求 B 尾部", 925, 386, 190, 58, { fill: "white" });
    arrow(s, root, sys, { fromSide: "bottom", toSide: "top", kind: "elbow" });
    arrow(s, sys, a, { fromSide: "bottom", toSide: "top", kind: "elbow" });
    arrow(s, sys, b, { fromSide: "bottom", toSide: "top", kind: "elbow" });
    pill(s, "核心问题：KV 池满了，哪些叶子该留下？", 704, 520, 462, 44, { fill: C.accentLight, color: C.accent });
    addFooter(s, 1);
  }

  // 2
  {
    const s = p.slides.add();
    s.background.fill = "white";
    addTitle(s, "SGLang 缓存想避免重复 prefill", "相同 prompt 前缀已经算过一次，后续请求就应该复用这部分 KV cache");
    const req1 = box(s, "请求 1\nsystem + 示例 + 问题 A", 92, 230, 265, 90, { fill: C.light, bold: true });
    const cache = box(s, "前缀 KV cache\n存进 KV 池", 508, 228, 260, 94, { fill: C.blueLight, line: C.blue, bold: true });
    const req2 = box(s, "请求 2\nsystem + 示例 + 问题 B", 92, 416, 265, 90, { fill: C.light, bold: true });
    const hit = box(s, "命中 shared prefix\n只计算差异部分", 912, 324, 280, 102, { fill: C.greenLight, line: C.green, bold: true });
    arrow(s, req1, cache);
    arrow(s, req2, cache, { kind: "elbow", fromSide: "right", toSide: "left" });
    arrow(s, cache, hit);
    note(s, "命中率 = cached_tokens / prompt_tokens\n命中越高，prefill 越少，TTFT 通常越低。", 410, 512, 460, 86, { fontSize: 20 });
    addFooter(s, 2);
  }

  // 3
  {
    const s = p.slides.add();
    s.background.fill = "white";
    addTitle(s, "RadixCache 是按 token 前缀分叉的树", "公共前缀只存一份，分叉尾部挂成不同叶子");
    const root = box(s, "root", 570, 196, 120, 54, { fill: C.ink, color: "white", bold: true });
    const sys = box(s, "system prompt\n共享段", 500, 314, 260, 68, { fill: C.blueLight, line: C.blue, bold: true });
    const mmlu = box(s, "MMLU 学科 A\nfew-shot 尾部", 178, 488, 220, 78, { fill: "white" });
    const chat = box(s, "会话 17\n历史尾部", 530, 488, 220, 78, { fill: "white" });
    const tenant = box(s, "租户 3\n业务 prompt 尾部", 882, 488, 220, 78, { fill: "white" });
    arrow(s, root, sys, { fromSide: "bottom", toSide: "top", kind: "elbow" });
    arrow(s, sys, mmlu, { fromSide: "bottom", toSide: "top", kind: "elbow" });
    arrow(s, sys, chat, { fromSide: "bottom", toSide: "top", kind: "elbow" });
    arrow(s, sys, tenant, { fromSide: "bottom", toSide: "top", kind: "elbow" });
    pill(s, "内部节点因为还有子树，通常不能直接淘汰", 400, 608, 480, 42, { fill: C.accentLight, color: C.accent });
    addFooter(s, 3);
  }

  // 4
  {
    const s = p.slides.add();
    s.background.fill = "white";
    addTitle(s, "TreeNode 既是树结构，也是淘汰决策的信号源", "A1 读代码时要把字段分成三类看");
    const cols = [
      ["结构字段", "`parent`\n`children`\n`key`\n`value`", "决定前缀树如何分叉，value 指向 KV 索引。"],
      ["访问信号", "`last_access_time`\n`creation_time`\n`hit_count`\n`priority`", "LRU/LFU/FIFO/SLRU 都从这些字段取 priority。"],
      ["保护与容量", "`lock_ref`\n`evictable_size_`\n`protected_size_`", "在飞请求会保护节点，真实可淘汰容量会变化。"],
    ];
    cols.forEach((c, i) => {
      const x = 82 + i * 390;
      box(s, c[0], x, 214, 320, 52, { fill: C.ink, color: "white", bold: true, fontSize: 22 });
      note(s, c[1], x, 292, 320, 122, { fill: C.light, fontSize: 24, bold: true, align: "center" });
      addText(s, c[2], x + 10, 442, 300, 92, { fontSize: 19, color: C.muted });
    });
    addFooter(s, 4);
  }

  // 5
  {
    const s = p.slides.add();
    s.background.fill = "white";
    addTitle(s, "match_prefix 不只是查询，也可能 split 节点", "当匹配停在一条边的中间，RadixCache 会把共享前缀切成显式节点");
    addText(s, "split 前", 126, 192, 180, 34, { fontSize: 24, bold: true });
    const beforeRoot = box(s, "root", 128, 258, 112, 50, { fill: C.ink, color: "white", bold: true });
    const longEdge = box(s, "A B C D E", 320, 252, 250, 62, { fill: C.light, bold: true });
    arrow(s, beforeRoot, longEdge);
    addText(s, "请求只匹配 A B C", 330, 336, 240, 28, { fontSize: 18, color: C.accent });

    addText(s, "split 后", 736, 192, 180, 34, { fontSize: 24, bold: true });
    const afterRoot = box(s, "root", 724, 258, 112, 50, { fill: C.ink, color: "white", bold: true });
    const abc = box(s, "A B C\n共享前缀", 906, 244, 170, 78, { fill: C.blueLight, line: C.blue, bold: true });
    const de = box(s, "D E\n原尾部", 958, 406, 138, 68, { fill: "white" });
    arrow(s, afterRoot, abc);
    arrow(s, abc, de, { fromSide: "bottom", toSide: "top", kind: "elbow" });
    note(s, "结果：共享前缀变成内部节点，后续更容易复用，也更难被直接淘汰。", 320, 520, 650, 66, { fill: C.accentLight, fontSize: 20 });
    addFooter(s, 5);
  }

  // 6
  {
    const s = p.slides.add();
    s.background.fill = "white";
    addTitle(s, "insert 把新 token 挂成叶子，并更新淘汰信号", "插入不是简单追加，沿途节点会更新访问时间、命中次数和优先级");
    const steps = [
      ["1", "沿树匹配已有前缀", "更新 last_access_time"],
      ["2", "必要时 split 边", "暴露共享前缀节点"],
      ["3", "剩余 token 创建叶子", "evictable_size_ 增加"],
      ["4", "沿途更新 hit_count / priority", "给策略提供信号"],
    ];
    let prev = null;
    steps.forEach((st, i) => {
      const x = 82 + i * 292;
      const head = box(s, st[0], x, 248, 52, 52, { geometry: "ellipse", fill: C.ink, color: "white", bold: true, fontSize: 24 });
      const card = box(s, `${st[1]}\n${st[2]}`, x + 24, 342, 220, 116, { fill: i === 2 ? C.greenLight : C.light, line: i === 2 ? C.green : C.rule, fontSize: 19, bold: i === 2 });
      arrow(s, head, card, { fromSide: "bottom", toSide: "top", kind: "elbow" });
      if (prev) arrow(s, prev, head, { fromSide: "right", toSide: "left" });
      prev = head;
    });
    note(s, "容量统计按 token，不按节点。长叶子被淘汰会释放更多 KV 空间。", 308, 548, 664, 54, { fill: C.accentLight, color: C.accent, bold: true, align: "center" });
    addFooter(s, 6);
  }

  // 7
  {
    const s = p.slides.add();
    s.background.fill = "white";
    addTitle(s, "evict 只在可淘汰叶子集合里选择", "策略看到的不是整棵树，而是当前 unlocked live leaves");
    const treeRoot = box(s, "root", 120, 232, 100, 46, { fill: C.ink, color: "white", bold: true });
    const shared = box(s, "共享前缀\n内部节点", 96, 340, 150, 70, { fill: C.blueLight, line: C.blue, bold: true });
    const leaf1 = box(s, "leaf A\n可淘汰", 52, 504, 126, 62, { fill: C.greenLight, line: C.green, bold: true });
    const leaf2 = box(s, "leaf B\n可淘汰", 210, 504, 126, 62, { fill: C.greenLight, line: C.green, bold: true });
    arrow(s, treeRoot, shared, { fromSide: "bottom", toSide: "top", kind: "elbow" });
    arrow(s, shared, leaf1, { fromSide: "bottom", toSide: "top", kind: "elbow" });
    arrow(s, shared, leaf2, { fromSide: "bottom", toSide: "top", kind: "elbow" });
    const heap = box(s, "heapq\n按 get_priority 排序", 515, 346, 240, 90, { fill: C.light, bold: true, fontSize: 22 });
    const victim = box(s, "弹出 victim\n释放 len(value) token", 930, 336, 260, 112, { fill: C.accentLight, line: C.accent, bold: true, fontSize: 22 });
    arrow(s, leaf1, heap, { fromSide: "right", toSide: "left", kind: "elbow" });
    arrow(s, leaf2, heap, { fromSide: "right", toSide: "left", kind: "elbow" });
    arrow(s, heap, victim);
    note(s, "如果父节点删完子节点后也变成 unlocked leaf，它会级联加入 heap。", 385, 534, 610, 58, { fontSize: 20 });
    addFooter(s, 7);
  }

  // 8
  {
    const s = p.slides.add();
    s.background.fill = "white";
    addTitle(s, "lock_ref 会让真机可淘汰池小于离线直觉", "并发请求持有节点时，节点从 evictable 转到 protected");
    const evictable = box(s, "evictable_size_\n可淘汰 token", 128, 268, 270, 112, { fill: C.greenLight, line: C.green, bold: true, fontSize: 23 });
    const protectedB = box(s, "protected_size_\n受保护 token", 886, 268, 270, 112, { fill: C.redLight, line: C.accent, bold: true, fontSize: 23 });
    const lock = box(s, "inc_lock_ref(node)\n在飞请求开始", 498, 248, 285, 70, { fill: C.light, bold: true, fontSize: 20 });
    const unlock = box(s, "dec_lock_ref(node)\n请求结束释放", 498, 394, 285, 70, { fill: C.light, bold: true, fontSize: 20 });
    arrow(s, evictable, lock);
    arrow(s, lock, protectedB);
    arrow(s, protectedB, unlock, { fromSide: "left", toSide: "right", kind: "elbow" });
    arrow(s, unlock, evictable, { fromSide: "left", toSide: "right", kind: "elbow" });
    note(s, "后续对齐模拟器和真机时，要解释并发导致的有效池缩小。", 316, 548, 650, 56, { fill: C.accentLight, color: C.accent, bold: true, align: "center" });
    addFooter(s, 8);
  }

  // 9
  {
    const s = p.slides.add();
    s.background.fill = "white";
    addTitle(s, "get_priority 能表达静态打分，却装不下完整 2Q", "LRU/LFU/SLRU 是单节点 priority；2Q 需要跨事件维护队列状态");
    const left = box(s, "现有接口\nget_priority(node)", 106, 238, 300, 82, { fill: C.light, bold: true, fontSize: 24 });
    const lru = box(s, "LRU\nlast_access_time", 92, 390, 142, 78, { fill: "white" });
    const lfu = box(s, "LFU\nhit_count", 262, 390, 142, 78, { fill: "white" });
    arrow(s, left, lru, { fromSide: "bottom", toSide: "top", kind: "elbow" });
    arrow(s, left, lfu, { fromSide: "bottom", toSide: "top", kind: "elbow" });
    const a1in = box(s, "A1in\n试用 FIFO", 642, 224, 158, 76, { fill: C.blueLight, line: C.blue, bold: true });
    const a1out = box(s, "A1out\n幽灵队列", 864, 224, 158, 76, { fill: C.accentLight, line: C.accent, bold: true });
    const am = box(s, "Am\n主 LRU", 754, 420, 158, 76, { fill: C.greenLight, line: C.green, bold: true });
    arrow(s, a1in, a1out, { color: C.accent });
    arrow(s, a1out, am, { fromSide: "bottom", toSide: "top", kind: "elbow", color: C.green });
    arrow(s, a1in, am, { fromSide: "bottom", toSide: "left", kind: "elbow", color: C.green });
    note(s, "2Q 需要 on_insert / on_hit / on_evict / on_split。\n这就是 A5 要扩展接口的原因。", 610, 548, 468, 74, { fontSize: 20, fill: C.light });
    addFooter(s, 9);
  }

  // 10
  {
    const s = p.slides.add();
    s.background.fill = "white";
    addTitle(s, "读 A1 时抓住三条主线", "后续 A3-A5 的设计都会回到这三条机制");
    const cards = [
      ["只淘汰叶子", "策略差异主要发生在叶子层。\n共享前缀成为内部节点后会被结构性保护。"],
      ["容量按 token 计算", "长叶子释放更多空间。\n命中率和淘汰效果不能只看节点数。"],
      ["接口目前无状态", "get_priority 只能给单节点打分。\n完整 2Q 需要事件钩子和幽灵队列。"],
    ];
    cards.forEach((c, i) => {
      const x = 92 + i * 382;
      box(s, c[0], x, 226, 300, 62, { fill: C.ink, color: "white", bold: true, fontSize: 25 });
      note(s, c[1], x, 326, 300, 148, { fill: i === 2 ? C.accentLight : C.light, fontSize: 20 });
    });
    pill(s, "下一步：用 A2 的 KV 池尺度，设计 A3 的四类 trace 负载。", 312, 566, 656, 46, { fill: C.blueLight, color: C.blue, fontSize: 18 });
    addFooter(s, 10);
  }

  return p;
}

async function writeBlob(filePath, blob) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await fs.writeFile(filePath, new Uint8Array(await blob.arrayBuffer()));
}

async function main() {
  await fs.mkdir(previewDir, { recursive: true });
  await fs.mkdir(path.dirname(finalPptx), { recursive: true });
  const presentation = createDeck();

  for (const [index, slide] of presentation.slides.items.entries()) {
    const stem = `slide-${String(index + 1).padStart(2, "0")}`;
    const png = await presentation.export({ slide, format: "png", scale: 1 });
    await writeBlob(path.join(previewDir, `${stem}.png`), png);
    const layout = await slide.export({ format: "layout" });
    await fs.writeFile(path.join(previewDir, `${stem}.layout.json`), await layout.text(), "utf8");
  }

  const montage = await presentation.export({ format: "webp", montage: true, scale: 1 });
  await writeBlob(path.join(previewDir, "montage.webp"), montage);
  const pptx = await PresentationFile.exportPptx(presentation);
  await pptx.save(finalPptx);
  console.log(`Wrote ${finalPptx}`);
  console.log(`Preview ${previewDir}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
