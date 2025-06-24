# Sing-box 配置模板仓库

这是一个模块化的 [sing-box](https://sing-box.sagernet.org/) 配置项目，支持从订阅生成配置，按需启用模块，并使用 GitHub Actions 自动构建和发布。

## 🚀 使用说明

```bash
# 1. Fork 本仓库（建议设置为私有）
# 2. 克隆你的仓库
git clone git@github.com:<your-username>/singbox-configs.git
cd singbox-configs

# 3. 切换到对应分支（v12 或 v11）
git checkout v12    # 或者 git checkout v11

# 4. 编辑订阅地址（每行一个）
nano subscription.txt

# 5. 选择启用模块（保留需要的 features/*.yaml）

# 6. 提交更改
git add .
git commit -m "update config"
git push
```

## 📦 分支说明

- `main`：主文档分支（不包含配置）
- `v12`：适用于 sing-box 1.12 的配置模板（推荐）
- `v11`：适用于 sing-box 1.11 的配置模板

## ⚙️ 自动构建说明

配置好订阅和模块后，GitHub Actions 将会：

1. 下载订阅并生成 `outbounds.yaml`
2. 合并基础配置与模块，生成 `build/final.json`
3. 可选：上传最终配置到你的私有 Gist

可在 GitHub → Actions 页面中手动触发构建或等待自动运行。

