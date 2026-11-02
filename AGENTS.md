# APT独立维护与发布

先读SKILL.md、meta.json、features.json、manifest.json、release-assets.json及相关源码和测试。

本技能唯一发布仓库是 https://github.com/T8mars/Apt-Replacement-Skill 。不得推送到video-replacement-skill-factory-T8或混入其他技能。保留wuwukasi原始LICENSE、原作者链接和视频署名，明确T8star的优化与维护贡献。

Git只发布manifest中的文本/源码成员及发布索引；44段原片、原音轨和原包示例图仅随完整技能ZIP分发，不作为单独素材发布。Release只用tools/build_release.py构建并核对原包媒体哈希。第三方可执行程序不上传；本机已有便携FFmpeg可以保留，公共包使用用户自己的FFmpeg/ffprobe。

任何目录/大小写的ROADMAP.MD、API Key、Token、凭据文件、runtime.json、账本、请求/签名URL、个人图片、候选和成片禁止进入Git或Release。不得递归暂存整个工作区。只同步发布白名单，提交前检查staged、推送前检查全部outgoing提交；保留远端历史，不使用force push。

用户已授权本技能发布到上述专属仓库。后续APT维护在这里更新，中英文README、版本、资产索引与manifest一致；factory仍使用自己的独立仓库。安装、检查、打包和发布不提交付费生成。
