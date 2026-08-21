# Nýtt frá stjórnarráðunum

GitHub Actions-vakt, sum kannar almennar føroyskar stjórnarráðssíður eina ferð um dagin.

Skipanin brúkar ikki SMTP. Tá okkurt nýtt verður funnið, stovnar hon eitt GitHub Issue. GitHub sendir síðani notification-email til tey, sum watch'a repo'ið.

## Fílur

- `.github/workflows/check.yml` - GitHub Actions workflow
- `monitor.py` - Python-scriptið
- `sources.yml` - keldur, sum verða kannaðar
- `state.json` - goymir, hvat longu er sæð
- `requirements.txt` - Python-pakkar

## Test

1. Upload'a innihaldið í hesi mappuni til GitHub-repo.
2. Tryggja at `.github/workflows/check.yml` er við.
3. Far til Actions.
4. Vel **Nýtt frá stjórnarráðunum**.
5. Trýst **Run workflow**.

## T-postur

Set repo'ið á **Watch -> All Activity**. GitHub sendir notification-mail, tá eitt issue verður stovnað.
