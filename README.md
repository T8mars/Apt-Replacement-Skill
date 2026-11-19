# APT全自动人物替换复刻 · APT Character Replacement Skill

## 调用入口与优惠

| 平台 | 入口 | 优惠 |
| --- | --- | --- |
| 贞贞 AI | [贞贞 AI 调用](https://www.zzai.app) | 免费 GPT Image 2.6 |
| RunningHub | [国内站](https://www.runninghub.cn?inviteCode=kol01-rh099) · [国际站](https://www.runninghub.ai?inviteCode=rh-v1121) | 每日 3 次免费 H3 及优惠券 |
| 晨羽 | [晨羽调用](https://www.chenyu.cn/console/login?invitationCode=NGT5S4) | T8 专属优惠券，见下表 |

| 晨羽优惠 | 数量或领取条件 | 券码 |
| --- | --- | --- |
| 0.1 = 5 | 300 张 | `W6TGFF` |
| 30 = 45 | 300 张 | `T8AIGC` |
| 50 = 100 | 每位粉丝均可领取，每个账号限领一次 | `50VS50` |

更多镜像陆续更新，可搜索 **t8star**。

## 选择生成渠道

每次收到新的一组参考图，先确认使用 RunningHub、贞贞 AI 还是晨羽。用户已指定时直接采用。恢复已有任务时沿用制作目录中的渠道和任务号。在新制作目录运行以下三条命令中的一条，选择渠道这一步不计费。

```powershell
python channels.py select --provider rh
python channels.py select --provider zhenzhen --key-file "C:\MyPrivate\zhenzhen.key"
python channels.py select --provider chenyu --key-file "C:\MyPrivate\chenyu.key"
```

两种新渠道各自使用所选平台的私有 Key；文件放在技能和制作目录之外。也可以省略 `--key-file`，使用 `ZZ_API_KEY_FILE` 或 `CHENYU_API_KEY_FILE` 指向私有文件。贞贞 AI 使用 `minimax-h3-comfyui-charswap`，把有序图片 URL 写入 `images`，运动视频和帧数放在 `metadata`。晨羽使用已发布的「Wuwu-视频角色替换」工作流，先校验版本，将图片分开上传并按当前镜头角色顺序绑定节点。

每段保留原始动作帧。渠道需要补帧时，仅给 24 fps 提交副本追加末帧，最终仍按原帧表合片。提交中断时，已取得任务号的继续查询；晨羽可用 `python channels.py reconcile --attempt <本地尝试ID>` 恢复原订单。贞贞 AI 在平台核对该镜头的原任务号后，再添加 `--task-id <原任务号>`。

**版本 / Version: 1.3.0** · **Skill ID: `apt-character-replacement`**

[中文使用说明](#中文使用说明) · [English guide](#english-guide) · [完整技能包 / Complete skill ZIP](https://github.com/T8mars/Apt-Replacement-Skill/releases/latest/download/apt-character-replacement.zip)

**感谢原作者 wuwukasi：** [B站主页](https://space.bilibili.com/670281046)  
**优化与维护 T8star：** [B站主页](https://space.bilibili.com/385085361)

基于 wuwukasi「全自动生成APT／复刻包」整理和优化，保留原作者许可、来源与视频署名。优化版增加独立任务准备、私有密钥读取、共享3并发恢复、完整输出审片、角色边缘复查、像素校验与一次编码合片。本项目不宣称原包及素材为 T8star 独立原创。

Based on wuwukasi's original APT recreation package. Original attribution, license and video credits are retained. T8star maintains the skill integration and workflow improvements; the original package and media are not presented as unrelated original work by T8star.

## 中文使用说明

### 这是做什么的

给 Codex **两张人物参考图和所选渠道的私有 Key 文件路径**，按这套已拆好的 APT 原片替换人物，复核后输出保留原音轨的视频。支持同片换新人物和两个人物对调。

| 项目 | 内容 |
| --- | --- |
| 固定原片 | 001–044，共44段；完整素材随技能包提供 |
| 实际生成 | 40段；002、004、007、017保留原片 |
| 最终视频 | 2316帧，24000/1001 fps，约96.60秒，1920×1080 |
| 生成服务 | RunningHub 海外单图／双图应用、贞贞 AI、晨羽 |
| 默认策略 | 3并发、一采1MP；按原镜头，不固定切5秒；完整输入≤10秒 |

这是**固定APT素材的换角技能**。其他新原视频应另做镜头分析，不能直接套用本包44段表。

### 1. 下载与安装

1. 下载 [完整技能包 apt-character-replacement.zip](https://github.com/T8mars/Apt-Replacement-Skill/releases/latest/download/apt-character-replacement.zip)。它包含技能、44段原片、原音轨、原包示例图及许可证。
2. 将解压后的 `apt-character-replacement` 文件夹放到 Codex 的技能目录，例如 `%USERPROFILE%\.agents\skills\apt-character-replacement`；已设置 `CODEX_HOME` 的用户也可以放到 `%CODEX_HOME%\skills\apt-character-replacement`。已有版本先备份，保留正在制作的独立任务。
3. 安装 **Python 3.10+、FFmpeg和ffprobe**，并安装依赖：

   ```powershell
   python -m pip install -r "C:\你的技能目录\apt-character-replacement\requirements.txt"
   ffmpeg -version
   ffprobe -version
   ```

   FFmpeg请从[官方下载安装入口](https://ffmpeg.org/download.html)获取，确保两个命令可用。公共安装包不包含第三方可执行文件；已有便携FFmpeg目录也可继续使用。
4. 在 Codex 新对话中调用 `$apt-character-replacement`。如果尚未显示，重新打开会话，或直接提供本地 `SKILL.md` 路径。

**推荐 Windows。** 当前生产调度使用 Windows 文件锁；其他系统可查看源码、分析和跑离线检查，完整生产调度需要适配相应系统的锁机制。

GitHub 的仓库及自动生成的 `Source code (zip)` 提供源码与说明。包含原片的完整安装包位于 Releases，文件名为 **apt-character-replacement.zip**；这是正常制作所需的包。

### 2. 准备账号与两张图

- 选 RH 时需要 RunningHub 账号及能调用相应应用的 API Key。当前生成适配器使用海外站：[注册 RunningHub](https://www.runninghub.ai/?inviteCode=rh-v1121)。国内注册入口为 [runninghub.cn](https://www.runninghub.cn?inviteCode=kol01-rh099)，当前脚本不会自动切换到国内接口。
- 准备两张清楚的人物图，分别作为一号和二号。多视图设定图可用；脸、头发、体型和服装越清楚，越便于保持身份。
- Key 保存在技能目录和制作目录**之外的私有文本文件**，例如 `C:\MyPrivate\runninghub_key.txt`，向 Codex 提供文件路径即可。不要上传到GitHub或把它写进提示词。
- 安装和离线检查不调用生成；正式制作由所选渠道计费。

原包中的两张图仅用于示例。每次新任务使用你本次提供的两张图；明确要求复用时沿用，避免反复索图。

### 3. 直接这样对 Codex 说

附上两张图后，复制这段话并替换私有Key路径：

```text
使用 $apt-character-replacement 制作APT换角视频。
第一张图是一号，第二张图是二号。
RunningHub Key文件：C:\MyPrivate\runninghub_key.txt
保留原片动作、镜头、场景和原音轨，人物外观按参考图。
按3并发执行，问题片段比较不同修复方案，完成复核后合片。
```

人物对调时说：

```text
还是刚才两个人，一号和二号对调，再做一个新版本；保留原动作和镜头。
```

Codex会建立新的独立制作目录，核对图像映射、写40份提示词、检查输入和当前应用节点，生成、下载、逐段复核并合片。任务中断后让它**继续原目录**，保留原taskId恢复；不要删除账本重新提交。

### 4. 在哪里拿成片

```text
<本次制作目录>\完成分段\最终组装\APT_final_Made-by-wuwukasi.mp4
```

同目录保留原作者 `LICENSE.txt`；任务目录保存候选、失败证据及当前选择。人脸、动作、遮挡、手袖、道具和镜头接点仍需按当前结果实际复核。队列满时等待恢复，下载失败恢复原任务；技术成功不自动代表画面通过。

### 命令行检查（可选）

正常使用可交给 Codex。需要自行检查时，在技能目录运行：

```powershell
python scripts/apt_project.py check
python scripts/apt_project.py init --project "D:\APT_Project\run01" --references "D:\Pictures\person1.png" "D:\Pictures\person2.png" --key-file "C:\MyPrivate\runninghub_key.txt"
```

`init`只准备任务，不提交生成。源码仓库可使用 `python scripts/apt_project.py check --source-only` 核对源码，同时明确报告缺少的完整包素材。更详细的执行、恢复和审片方法见 [SKILL.md](SKILL.md) 与 [工具说明](references/runtime-and-review-tools.md)。

## English guide

### Choose a generation provider

For each new pair of references, specify **RunningHub**, **Zhenzhen AI** or **Chenyu**. In the new production directory run exactly one of the following commands before preparing the queue. Resume in the same directory with the original account.

```powershell
python channels.py select --provider rh
python channels.py select --provider zhenzhen --key-file "C:\MyPrivate\zhenzhen.key"
python channels.py select --provider chenyu --key-file "C:\MyPrivate\chenyu.key"
```

Use your selected provider’s private key file, stored outside the skill and production folders. Zhenzhen uses the MiniMax H3 charswap model with ordered image URLs. Chenyu uploads a separate asset per role and binds each one to a workflow slot. Short clips receive a temporary final-frame hold when required. The final cut uses the original shot timing and soundtrack. Confirm the role mapping with a pilot before batching.

### Service links and offers

| Service | Access | Offer |
| --- | --- | --- |
| Zhenzhen AI | [Open Zhenzhen AI](https://www.zzai.app) | Free GPT Image 2.6 |
| RunningHub | [Mainland China](https://www.runninghub.cn?inviteCode=kol01-rh099) · [International](https://www.runninghub.ai?inviteCode=rh-v1121) | Three free H3 runs per day, plus coupons |
| Chenyu | [Open Chenyu](https://www.chenyu.cn/console/login?invitationCode=NGT5S4) | T8-exclusive coupons listed below |

| Chenyu offer | Availability | Coupon code |
| --- | --- | --- |
| 0.1 = 5 | 300 coupons | `W6TGFF` |
| 30 = 45 | 300 coupons | `T8AIGC` |
| 50 = 100 | Available to every fan, once per account | `50VS50` |

Search for **t8star** to find new mirror sites as they are added.

### What it does

Provide Codex with **two character reference images and your chosen provider’s private key file**. This skill replaces the two roles in the included APT sequence while preserving the original performance, shots, scene and soundtrack. Reuse the sequence with new characters, or swap the two role assignments.

The package contains 44 fixed source segments: 40 are generated and 002/004/007/017 pass through unchanged. The final film is 2316 frames at 24000/1001 fps, approximately **96.60 seconds**, at **1920×1080**. It is a template for this APT sequence, rather than a general replacement tool for arbitrary new footage.

The default is three concurrent jobs and 1MP generation. Segmentation follows the original shots; complete generation inputs, including holds and context, must stay within ten seconds.

### Install

1. Download the [complete apt-character-replacement.zip](https://github.com/T8mars/Apt-Replacement-Skill/releases/latest/download/apt-character-replacement.zip) from Releases. It includes the skill, all source segments, original audio, original example images and licenses. GitHub's automatic source archives contain code and documentation only.
2. Extract the `apt-character-replacement` folder into your Codex skills directory, for example `~/.agents/skills/apt-character-replacement`, or `$CODEX_HOME/skills/apt-character-replacement`. Back up an existing installation and keep active production runs separate.
3. Install Python 3.10+, [FFmpeg and ffprobe](https://ffmpeg.org/download.html), then run:

   ```text
   python -m pip install -r <skill-folder>/requirements.txt
   ffmpeg -version
   ffprobe -version
   ```

   Third-party executables are not redistributed in the public package. Existing local portable tools are supported.
4. Start a Codex conversation and invoke `$apt-character-replacement`, or provide the absolute path to its `SKILL.md`.

**Windows is the supported production platform.** The current dispatcher uses Windows file locking. Source inspection, analysis and offline tests can run on other systems; production locking needs a platform-specific adapter.

### Prepare your inputs

For the RH route, use a RunningHub account and a key with access to the configured AI applications. The implemented adapter targets [runninghub.ai](https://www.runninghub.ai/?inviteCode=rh-v1121). A domestic [runninghub.cn registration](https://www.runninghub.cn?inviteCode=kol01-rh099) does not automatically change the script's endpoint.

Keep your key in a private text file **outside the skill and production folders**, and give Codex the local file path. Never commit the key or put it into a prompt file. Installation and offline checks do not submit generation; an authorized production run is billed by the selected provider.

Supply two clear character images, labeled role 1 and role 2. Original package images are examples, not silent defaults for new projects. Reuse previously supplied images only when requested.

### Ask Codex to produce the video

Attach both images and use:

```text
Use $apt-character-replacement to make the APT replacement video.
Image 1 is role 1; image 2 is role 2.
RunningHub key file: C:\MyPrivate\runninghub_key.txt
Preserve the source actions, camera, scene and original audio.
Use the supplied characters, maintain three concurrent jobs,
review failed segments with distinct repair methods, then assemble.
```

For a role swap:

```text
Reuse the same two characters, swap roles 1 and 2, and create a new version.
Preserve the source actions and shots.
```

Codex prepares an isolated run, validates inputs, writes the prompts, generates and downloads candidates, reviews the actual output and assembles selected segments. After an interruption, resume the **same run** and existing task IDs. Busy queues wait; download failures recover the original job instead of creating another paid generation.

### Output and checks

The final file is:

```text
<run>/完成分段/最终组装/APT_final_Made-by-wuwukasi.mp4
```

Original author credits and `LICENSE.txt` are retained. Identity, motion, occlusion, props and seams require actual review; a successful API response or decode is not a visual approval.

Optional local commands:

```text
python scripts/apt_project.py check
python scripts/apt_project.py init --project <new-empty-run> --references <role1.png> <role2.png> --key-file <outside-private-key-file>
```

`init` prepares files only. In a source-only checkout use `check --source-only`; the command reports which complete-package assets are missing. See [SKILL.md](SKILL.md) and [runtime/review documentation](references/runtime-and-review-tools.md) for the detailed agent workflow.

## 署名与许可 / Attribution and license

- **原作者 / Original author:** [wuwukasi](https://space.bilibili.com/670281046). Original package: 「全自动生成APT／复刻包」.
- **优化与维护 / Optimization and maintenance:** [T8star](https://space.bilibili.com/385085361). Contributions include skill packaging, private credential handling, isolated runs, three-job recovery, full-output review, partial-role corrections, lossless verification and high-quality assembly.
- 原始许可完整保留于 [LICENSE.txt](LICENSE.txt)，原包副本见 [assets/template/LICENSE.txt](assets/template/LICENSE.txt)。The original license is retained unchanged in both locations.
- 原片、音乐和示例图归各自权利人，限许可约定的本项目复刻使用；不可单独提取传播或用于商业用途。Third-party media remains owned by its rights holders and is provided only within the complete licensed project package; do not extract, redistribute or commercially reuse it on its own.
- 不移除原作者、来源、许可或视频内署名。Retain the original author, source, license and in-video credits. This publication does not grant additional rights to third-party media.

完整安装包附SHA256校验文件。发布仅来自此APT专属仓库，不混入其他技能、API Key、私有任务或个人生成结果。

Complete releases include a SHA256 checksum file. Only this APT skill is published here; keys, private task records, personal outputs and other skills are excluded.
