# 可靠运行与证据工具

适用于本技能新建的独立run，工具均从`assets/template`复制到run根目录。先读本次runtime.json与当前素材，不依赖历史制作目录。所有下述prepare/check及审片命令均不调用云端。

## 队列准备与执行

`rh_batch.py`保留原包配置、CAST和许可，旧提交入口已停用。实际生成使用`apt_runtime.py`，由同账户共享的私有SQLite台账约束3并发。默认台账与本机factory共用；这是本地账户对账，不是把APT发布到factory仓库。相同账户的其他工作也须使用同一台账、同一account_alias；网页手工任务和绕过台账的程序无法被该锁统计，开始前须对账，不能宣称锁能控制外部程序。

1. 只读取得当前AI应用节点快照，保存`接口快照/app-<应用ID>.json`。本适配器只实现已验证的runninghub.ai单/双图应用；CN模式不得静默走海外接口，改接口须单独验证。
2. 完成并检查本次40份六段提示词与参考图映射。每个候选写入`approved-queue.json`的`jobs`。普通任务window_id=原段号；修复候选用新的唯一名字，如`030_method_A`，另写source_segment=`030`，同一原段可同时排三个不同方法。不改变原段切分，不覆盖旧候选。主40段排在修复队列前，避免一个难段阻塞其他未提交段。
3. 运行`python apt_runtime.py prepare`：完整读取输入、核音轨、核≤10秒，计算不可变摘要，将semantic_review置pending。实际检查当前身份、动作、画幅、道具和输入方法后，才由制作代理写入passed、对应input_digest和具体notes；该步骤记录代理已完成的审查，不要求用户再次确认。
4. 在runtime.json记录已有用户制作请求：production_authorized=true、production_request=原请求摘要、approved_segments=本次已审查候选ID；安装默认均未授权。运行`python apt_runtime.py check`，通过后`python apt_runtime.py run`。status只读本地状态；run --once只处理一轮。断线后重启同一run，不能清台账重新生成。

普通双人任务示例（原001帧数以本次媒体实测为准）：

```json
{
  "jobs": [{
    "window_id": "001",
    "video_path": "补齐生成用/001 141.mp4",
    "prompt_path": "提示词/001.txt",
    "reference_paths": ["替换用参考图/一号.png", "替换用参考图/二号.png"],
    "generation_frames": 141,
    "generation_fps": "24",
    "schema_path": "接口快照/app-2107845954833907713.json",
    "profile": {
      "kind": "legacy-ai-app", "app_id": "2107845954833907713", "instance_type": "plus",
      "resolution_selector": {"aspect_ratio": "16:9 (Widescreen)", "megapixels": 1, "aspect_node_ids": ["115", "214"]}
    }
  }]
}
```

单人应用ID为2107844752011010050；仅二号单人仍只上传二号到Picture1。原图裁图须写reference_crops，字段source_path、source_sha256、crop=[左,上,右,下]；工具逐像素核对原图裁剪，禁止换成生成肖像冒充原参考。

变换/裁剪/慢速/引导输入另提供source_contract_path：JSON至少含source_segment、method、action_frames（实际动作输入帧及其原帧对应）、source_action_review=`passed`、dependency_paths（全部来源、姿态引导图、转换配置等）。所有依赖一起纳入摘要。人工源动作复核不能由写入passed这个字段替代，脚本只核合同及字节，无法判断引导人物是否正确。新增完整输入重新prepare/check，已受理输入严禁修改；运行队列只能追加完整审查的新条目。

调度顺序是查询→补满3个执行位→下载。每次新提交上传新临时素材；已受理ID恢复不重新POST或上传。队列忙冷却至少60秒；未知POST保留SUBMISSION_UNKNOWN并停止新提交，先在私有台账对账原taskId。下载/严格解码失败只重取原ID；执行连续失败3次暂停检查输入，画面质量没有固定3次上限。视觉失败须记录失败证据后，在台账标记VISUAL_FAILED，再追加新方法；不能让下载状态自动触发质量重投。私有台账不放技能或制作目录，不复制、压缩或发布。

## 看完整实际输出

```text
python review_media.py --video <候选绝对路径> --out <新的证据目录> --source <对应原段绝对路径> --native-all
python review_media.py --video <候选> --out <新的证据目录> --source <原段> --map <实测映射.json> --roi <固定裁图.json>
```

工具从首帧解到真实末帧生成完整连续页，记录实际帧数、PTS、重复帧统计；不按输入帧数、review_frames或前置保持数截断。native-all保存所有实际原尺寸帧。ROI示例`[{"name":"woman","box":[400,100,1100,900]}]`，手动按当前画面设定，覆盖全部真实输出；固定框仍可能漏人，必须检查覆盖并补框。不能仅凭自动追踪或五张概览验收。

实测映射包含output_indices、source_indices、action_start_middle_end_review（具体姿态证据）；有内部切点时成对提供source_cut_before/output_cut_before。工具拒绝越界、动作顺序倒退、跨切点和缺失开始/中段/结束记录，生成每个选定姿态的源/输出对照。它不自动选择动作帧，不能以线性抽样或静态身份锚点填满缺失动作。重复帧统计也不是视觉判定。

## 无损修整、组装与验收

RGB局部修整先保存逐帧规范PNG及计划摘要，再运行`verify_rgb.py --pngs <有序零填充PNG目录> --video <无损视频> --out <验证.json>`。它使用独立FFmpeg普通CPU完整解码，与每张规范PNG的RGB字节核对；编码器设置、遮罩外像素证明和视觉检查另外记录。“FFV1”三个字不能替代像素验证。

选择清单为`制作分析/selected-candidates.json`，每个segments[NNN]含output绝对路径、output_sha256、attempt、native_review/action_review/output_clock_review=`passed`、reference_identity_sha256（当前一号/二号原图摘要，固定两个槽位）、actual1x状态。已选文件必须是准确原帧数的无损派生，保存每帧来源与任何转换记录；不是含前置上下文的原始云输出。

依次使用：

```text
python assemble-reviewed.py --plan-only
python preflight-assembly-decoder.py
python prepare-lossless-assembly-inputs.py
python assemble-reviewed.py
python inspect-final-assembly.py
```

整理前停本run的本地watch写入器，不能停云任务；中间检查点绑定源哈希，旧文件保留。默认使用本机已定位的FFmpeg普通CPU严格解码与libx264一次最终编码；确有兼容问题才在runtime.encoder_path指定已验证编码器。不可为了让编码通过关闭严格错误检查。自动核44段/2316帧、24000/1001逐帧PTS、等比例适配、AAC原包前缀及原许可；生成全部43接点和18原尺寸端点供实际查看。文件已存在时停止，改用新的run或明确的新产物版本，禁止覆盖旧交付。

输出检查、原尺寸视觉、动作时钟、接点实际查看、整片原速播放分别记录。证据准备默认pending；只有实际看过才改passed。后台工作不操作用户桌面，聊天内交付真实成片供原速确认。
