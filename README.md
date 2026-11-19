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


## Ministry Check PWA (fyrsta útgáva)

Ein statisk PWA liggur í `docs/`. Hon krevur onga aðra tænastu enn GitHub Pages.

1. Legg nýggju fílurnar á GitHub, helst í eini serstakari branch fyrst.
2. Far til **Settings → Pages → Build and deployment** og vel **Deploy from a branch**, `main`, `/docs`.
3. GitHub Pages-vísingin verður tá tøk á Pages-adressuni hjá repositorynum.
4. `monitor.py` leggur greinarnar í `docs/feed.json`, **eftir at** GitHub Issue er stovnað. Tað tryggjar, at sama útsendingarkriterium verður brúkt til bæði t-post og appina.
5. `.github/workflows/check.yml` commit'ar nú bæði `state.json` og `docs/feed.json`.

**Týdningarmikið:** Fyrsta `feed.json` er tóm. Verandi `state.json` inniheldur bert hash-eyðmerkingar, so gamlar greinar kunnu ikki endurskapast úr tí. Appin fær tí sín fyrsta lista, tá næstu nýggju tíðindini verða funnin. GitHub Pages kann vera alment atkomuligt; legg tí bert almennar tíðindaupplýsingar í `feed.json`.

**Push-fráboðanir:** Eru ikki virknar í hesi útgávuni. Tær krevja eina trygga skrásetingarleið og trygga goymslu av push-subscriptions; loysnin skal ikki lata privat VAPID-lyklar ella subscriptions liggja í almennari GitHub Pages-fílu.
