# FO Ministry Watch

Daglig GitHub Actions-tænasta, sum kannar almennar føroyskar stjórnarráðssíður og sendir teldupost, um nýtt týdningarmikið er komið.

## GitHub Secrets

Legg hesar secrets í repo: Settings → Secrets and variables → Actions → New repository secret.

- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASS`
- `MAIL_FROM`

Móttakarin er settur í workflow/prompt til `samskifti@glasir.fo`, men kann broytast við `MAIL_TO` secret, um ynskt.

## Koyring

Workflowið koyrir eina ferð um dagin og kann eisini koyrast manuelt við `workflow_dispatch`.
