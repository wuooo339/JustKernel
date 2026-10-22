# 每次提交的邮件通知

`push email notification` 工作流在 `checks` 完成后，对本仓库每次 push 发送一封邮件。
成功、失败和取消都会汇总；Windows / macOS / Linux 不会分别发信。默认收件人是合作者提交记录中的
`gresces@foxmail.com`。`main`、`refactor` 及其他运行 `checks` 的分支均适用；PR 检查和重复运行不另发邮件。
工作流必须保留在仓库默认分支。提交中包含跳过 CI 的指令、未触发 `checks` 时，不会产生这封汇总通知。

邮件包含仓库、分支、提交 SHA、作者、提交说明、CI 总结果、各平台结果、失败步骤及 GitHub 链接。
仓库原有的 GitHub 个人通知设置保持不变；额外通知不会修改任何合作者账号的邮箱设置。

## 配置一次发件服务

收件邮箱不等于发件服务；GitHub Actions 的 `GITHUB_TOKEN` 无法直接发送任意电子邮件。
请在 [Actions Secrets and variables](https://github.com/wuooo339/JustKernel/settings/secrets/actions)
配置可用的 SMTP 发件服务。密码、邮箱授权码或邮件服务凭据只能填入 Secrets。

| 位置 | 名称 | 内容 |
| --- | --- | --- |
| Secrets | `SMTP_USERNAME` | 发件服务账号，通常为发件邮箱 |
| Secrets | `SMTP_PASSWORD` | SMTP 授权码或发件服务密码，按供应商要求 |
| Variables | `SMTP_HOST` | 发件服务的 SMTP 服务器 |
| Variables | `SMTP_PORT` | 默认 `465`；STARTTLS 通常为 `587`，以供应商为准 |
| Variables | `SMTP_SECURITY` | 默认 `ssl`，也支持 `starttls`，不支持明文认证 |
| Variables | `SMTP_FROM` | 可选；发件邮箱，默认取 `SMTP_USERNAME` |
| Variables | `NOTIFY_EMAIL` | 默认 `gresces@foxmail.com`；可改为 `guoyangfan2003@outlook.com` |

未配置 SMTP 时工作流会明确显示 `Waiting for SMTP configuration`，不会发送邮件。
配置后，在 **Actions → push email notification → Run workflow** 手动运行一次测试；此操作会真实发一封测试邮件。
SMTP 接受邮件后，摘要显示 `Mail service accepted`；是否进入收件箱或垃圾邮件仍取决于邮件服务。
邮件发送失败会明确报错，不盲目重试，以减少重复邮件。

## 执行范围

通知只读取 Actions 元数据，使用默认分支的受信任脚本，不检出触发分支、不执行其源码或下载其构建产物。
所需仓库权限仅为 `contents: read`、`actions: read`。不读取本地模型 Key、SSH 配置、浏览器登录态或运行记录。

无凭据本地验证：

```sh
python -m unittest discover -s .github/scripts -p 'test_*.py' -v
```
