# Ministry Check – samlað rætting (20.11.2026)

## Legg alt inn í EINARI broyting

1. Ger eitt avrit av repositorynum ella eina nýggja branch áðrenn upload.
2. Legg `monitor.py`, `push_sender.py`, `docs/` og `.github/workflows/` inn á røttu plássini. Varðveit mappuskipanina.
3. **Ikki yvirskriva** `state.json`, `sources.yml` ella `docs/feed.json`. Tær fylgja **ikki** við í pakkanum.
4. Ynskir tú at royna broytingarnar á eini branch, so er tað best fyrst; workflow við planlagdari koyring virkar bara á default branch.
5. Legg samansettu broytingarnar á `main` eftir royndir.
6. Koyr `Dagfør myndir í PWA` eina ferð: hetta dagførir dátur/útgávudagar/myndir í `docs/feed.json`, uttan GitHub Issues og uttan broyting í `state.json`. Kanna loggin.

### Hvat er við?

* `monitor.py`: Myndir, útdráttir, greinar og tryggari meting av útgávudegi úr greinamerking og avmarkaðum tíðarmerkjum. Dagfestingar verða **ikki gittar** úr tekstinum. `--repair-feed-images` dagførir myndir og útgávudagar í verandi feed.
* `docs/index.html`, `docs/sw.js`: Tvær síður – tíðindi og grein. Eingin niðasta valmynd, myndir, lesnar/goymdar greinar, framhaldandi sortering eftir váttaðum útgávudegi og ein push-knøttur, tá almennur VAPID-lykill er tøkur.
* `.github/workflows/check.yml`: Verandi 3 kanningar/dag, Issue/t-postur verður varðveittur. Push verður bert roynt eftir væleydnaðan commit við **nýggjum greinum** og bert tá PUSH_ENABLED er sett til true.
* `.github/workflows/repair-images.yml`: Verandi manuell metadata-rætting.
* `.github/workflows/push-test.yml`: Serstøk testkoyring við vilja, eingin tíðindakanning.
* `push_sender.py`: Push sendari, sum lesur GitHub Secrets, og samanber feed við síðsta commit.

## PWA á iPhone

Opna GitHub Pages-adressuna í Safari, vel Deil > Add to Home Screen > Add, og opna síðani appina frá heimaskíggjanum. iOS 16.4+ krevst fyri Web Push á heimaskíggja-PWA. Notifikationsloyvi verður biðið um við einum knøtti inni í appini, ikki við innlasting.

## Set push upp uttan aðra tænastu enn GitHub

**Push er sløkt, til hesi stigini eru framd.** GitHub Pages kann ikki sjálvt taka ímóti skrásetingum. Fyrsta telefonin verður tí skrásett við manuellari og vardari mannagongd.

1. Á **egnari Mac**: `python3 -m pip install cryptography` og síðani `python3 scripts/generate_vapid.py`. **Koyr hetta lokalt; ikki í GitHub Actions**, tí privati lykilin verður prentaður á skíggjan. **Deil ongantíð privata lykilin.**
2. Legg **bert almenna lykilin** í `docs/push-config.json` í `publicKey`. Commit hesa broytingina. Lat Page-deployment verða liðugt.
3. Opna appina frá iPhone-heimaskíggjanum; trýst `Fá push-fráboðanir` og síðani `Kopiera skráseting`.
4. Far til GitHub > repository > Settings > Secrets and variables > Actions > New repository secret. Stovna:
   - `PUSH_VAPID_PRIVATE_KEY`: privati lykilin frá lokalari koyring
   - `PUSH_VAPID_CONTACT`: t.d. `mailto:t-postadressa@eitt-domeni.fo` (tín egna galdandi teldupostadressa; ikki neyðugt at skriva hana í kotuna)
   - `PUSH_SUBSCRIPTIONS_JSON`: **tað, sum appin kopieraði** (eitt JSON-array; inniheldur endpoint og push-krypteringslyklar)
   - `PUSH_ENABLED`: fyrst `false`
5. Koyr **Actions > Royn push-fráboðan** við `PUSH_ENABLED=false`. Hetta skal siga, at push er sløkt.
6. Tá tú ert klárur at royna eina fráboðan, set `PUSH_ENABLED` til `true` og koyr **Actions > Royn push-fráboðan**. Verður boðið móttikið á iPhone, er push virkið.
7. **Ikki** leggja subscriptions í almenna JSON, GitHub Issues ella spjall. At knýta fleiri telefonir at krevur at `PUSH_SUBSCRIPTIONS_JSON` verður dagført við fleiri subscriptions í arraynum. Tær kunnu avmeldast á telefonini; tá skal GitHub Secret eisini dagførast.

## Verjandi avmarkingar

* Tað er ongin sjálvvirkandi skráseting/avmelding av telefonum, tí appin hevur ikki privatan API-móttakara.
* Um sending miseydnast, órógvar tað ikki teldupostskipanina. Fráboðanin verður heldur ikki sjálvvirkandi endursend.
* Fráboðanir kunnu verða seinkaðar ella avvístar av iOS, push-veitara ella telefonstillinum.
* Tað er eingin garanti fyri, at allir upprunavegir hava útgávudag ella mynd.
* Raðfesting við útgávudegi er neyvari enn við funnudegi, men gamlar greinar við ongari staðfestari dagfesting fara niðast.
