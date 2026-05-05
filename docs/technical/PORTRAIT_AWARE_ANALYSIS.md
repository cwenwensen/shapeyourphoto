# Portrait-Aware Analysis

日期：`2026-05-05`

## 目标

- 降低闪光灯人像、毕业照、合影照被误判为“欠曝”的概率。
- 在不引入新重依赖的前提下，让分析阶段区分“主体亮度”和“背景亮度”。
- `1.1.3` 当前目标分两层：
  - 第一层是“判断更准、少误修”。
  - 第二层是“有人像时优先按区域做轻微正确修复”，而不是继续走粗暴全局处理。
- 不做复杂人像美颜或身份识别。

## 设计约束

- 不修改现有启动方式、导入方式、拖拽、进度、输出目录和元数据保留主链路。
- 不依赖 `opencv`；当前实现使用 `Pillow + numpy` 完成轻量候选区域检测。
- 不做人脸身份识别，只估计疑似人脸/人像区域和主体亮度。

## 分析流程

1. 常规亮度、对比度、锐度、色彩和噪声统计保持不变。
2. 新增轻量人像候选检测：
   - 先按最长边缩放到约 `320px` 做快速检测。
   - 使用 `YCbCr + RGB` 的肤色阈值和简单形态学滤波生成候选区域。
   - 用连通域、面积、宽高比、位置和亮度做保守筛选。
3. 根据候选框与整图亮度分布估计：
   - `face_count`
   - `face_boxes`
   - `face_region`
   - `subject_region`
   - `background_region`
   - `highlight_region`
   - `face_luma_mean / face_luma_median`
   - `face_saturation_mean`
   - `subject_luma_estimate`
   - `background_luma_estimate`
   - `face_exposure_status`
   - `subject_exposure_status`
   - `background_exposure_status`
   - `portrait_exposure_status`
   - `portrait_scene_type`
   - `highlight_clipping_ratio`
   - `subject_background_separation`
   - `portrait_repair_policy`
4. 当检测到人像且主体亮度正常时，曝光判断会增加保护：
   - 不再仅因全图偏暗直接判定欠曝
   - 不再仅因大面积亮背景直接判定需要强全局压高光
   - 优先输出“主体曝光基本正常，背景偏暗但可作为氛围”
   - 对高调白墙、浅色建筑等场景优先输出“人物主体曝光基本正常，背景偏亮但不建议整体压暗”
   - 额外写入诊断标签，如 `portrait_subject_ok`、`dark_background`、`high_key_background`、`protect_high_key_background`

## 场景类型

- `normal_portrait`
  - 普通人像，主体与背景关系较中性。
- `dark_background_portrait`
  - 主体正常，背景偏暗，允许保留氛围，不应强行把背景抬亮。
- `high_key_portrait`
  - 主体正常，背景高亮或高调，优先保护白墙、浅色建筑、天空等高调背景。
- `backlit_portrait`
  - 背景更亮且主体相对受压，允许温和增强主体，但仍禁止把背景整体压灰。

## 修复联动

- `repair_planner.py`
  - 人像主体正常时，抑制把“欠曝”直接映射成强全局提亮。
  - 高调背景人像不再优先使用强全局压高光。
  - 第一版已接入的局部方法包括：
    - `portrait_local_face_enhance`
    - `portrait_subject_midcontrast`
    - `portrait_dark_clothing_detail`
    - `protect_high_key_background`
- `repair_ops.py`
  - `lift_shadows()` 对人像主体正常场景限幅，减少黑色服装和暗背景被抬灰。
  - `boost_contrast()`、`boost_vibrance()` 对人像保护场景做轻微收敛。
  - 新增基于粗 mask 的局部增强和背景保护，边缘通过羽化后再 alpha blend 合回原图。
- `repair_engine.py`
  - 人像场景会先生成保守强度候选，再做评分与回退。
  - 若候选让脸部、背景或服装指标变差，可自动降级或直接 no-op。
  - 所有跳过都会附带显式原因，例如“未选择任何修复方法”、“当前分析结果不建议自动修复”或“候选未优于原图”。
  - 修复后仍会做轻量安全检查，只提示不阻断保存。

## UI 与 Console

- 右侧诊断区会显示人像感知结论、主体/背景亮度估计和保护提示。
- Console 会追加：
  - 检测到多少张人脸或疑似人像主体
  - 当前按何种人像场景与修复策略判断
  - 候选强度是否被接受或回退
  - 本次跳过的明确原因
  - 修复后是否触发安全告警

## 当前边界

- 这是启发式检测，不保证每张图的人脸数量都完全精确。
- 如果服装、花朵、肤色相近物体很多，候选框可能偏多，但修复策略会优先依赖“脸部亮度是否正常”而不是单靠计数。
- 当前主体区仍是粗框，不是精细分割。
- `1.1.3` 更重视“不要把人像误修坏”，因此所有局部增强和候选强度都偏保守。
## 1.1.3 Maintenance Addendum: Face Validation And Cleanup Candidates

- 人脸检测现在明确分为 `raw_face_candidates` 与 `validated_face_boxes` 两层。
- `raw_face_candidates` 可以保留偏宽松的候选，但 portrait-aware policy、多人像评分和主体区域估计只消费 `validated_face_boxes`。
- `AnalysisResult.face_candidates` 会记录每个候选的 box、detector score、final confidence、accepted 状态和 rejection reasons，方便定位椅背文字、绿植纹理、手部、衣物边缘等误识别来源。
- 如果所有候选都被拒绝，`portrait_rejection_reason` 会尽量总结主要拒绝原因，供 Console 和后续维护排查使用。

## 1.1.3 Maintenance Addendum: portrait_out_of_focus

- 新增 `portrait_out_of_focus` 问题，用 validated face / subject 为核心评估对焦情况，而不是只看全图锐度。
- 该规则会综合脸部锐度、主体锐度、face ring 周边锐度和背景相对脸部的清晰度差。
- 当脸部明显虚焦、且背景或周边结构更清楚时，会输出高严重度问题，并给出 `不适合保留 / 建议删除` 的建议。

## 1.1.3 Maintenance Addendum: Generic Cleanup Candidates

- `AnalysisResult.cleanup_candidates` 用于承载通用“不适合保留”候选原因，不再把逻辑写死在人像虚焦里。
- 每个 cleanup candidate 至少包含：
  - `image_path`
  - `thumbnail_path`
  - `reason_code`
  - `reason_text`
  - `severity`
  - `confidence`
  - `source_issue`
- analyzer 负责产出候选；UI 负责展示与用户确认；文件操作层负责优先回收、失败时退回项目隔离目录。
- 当前已接入的高风险候选包括 `portrait_out_of_focus`、`global_out_of_focus`、`severe_overexposed` 和 `severe_underexposed`。
