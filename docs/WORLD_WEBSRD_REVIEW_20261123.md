# Worldwide HAM receiver expansion — November 23, 2026

Owner requests more worldwide HAM receivers, while KiwiSDR stays removed. This is a staged expansion, not audio verification. No central WebSDR.org directory dataset is copied. No new HTTP embedding exceptions, recording, retransmission, or automatic connections.

37 previous curated choices are preserved. Add **one HTTPS receiver-page candidate** and **six explicitly browser-only operator/club-published receiver links**. Total list: 44 choices (not 44 verified live audio feeds). Browser-only choices cannot be connected in the embedded WebSDR tuner under the unchanged transport policy.

| Name | Public source | Verification |
|---|---|---|
| Bordeaux · HAM (Bordeaux, France) | [Individual link](https://ham2.websdrbordeaux.fr/) · [Documentation](https://www.websdrbordeaux.fr/) | Public WebSDR HTML retrieved; decoded audio and in-app tuning unverified |
| LU6FLZ · Venado Tuerto (Santa Fe, Argentina) | [Individual link](http://lu6flz.no-ip.org:7999/) · [Documentation](https://www.lu3fv.com.ar/recursos) | Link documented; browser only; direct page/audio unverified |
| LU3DJ · Tres Arroyos 40m (Buenos Aires, Argentina) | [Individual link](http://lu3dj.ddns.net:8080/) · [Documentation](https://radioclubvillamaria.info/websdr/) | Link documented; browser only; direct page/audio unverified |
| LU3DJ · Tres Arroyos 20m (Buenos Aires, Argentina) | [Individual link](http://lu3dj.ddns.net:8081/) · [Documentation](https://radioclubvillamaria.info/websdr/) | Link documented; browser only; direct page/audio unverified |
| LU8FCJ · Villa Cañás (Santa Fe, Argentina) | [Individual link](http://el22.dyndns-blog.com:8080/) · [Documentation](https://radioclubvillamaria.info/websdr/) | Link documented; browser only; direct page/audio unverified |
| F8KCF · Romagny (Annemasse, France) | [Individual link](http://sdr.f8kcf.net:8901/) · [Documentation](https://f8kcf.net/accueil/) | Link documented; browser only; direct page/audio unverified |
| F8KCF · Mont Salève (Haute-Savoie, France) | [Individual link](http://sdr2.f8kcf.net:7489/) · [Documentation](https://f8kcf.net/accueil/) | Link documented; browser only; direct page/audio unverified |

Bordeaux has the original WebSDR HTML5 tuner controls and a public HTTPS endpoint; its additional cross-site widgets may not work under the isolated same-origin policy. No wider resource permission is proposed. See [operator page](https://ham2.websdrbordeaux.fr/) and [F5NIH receiver references](https://www.f5nih.fr/ecouter-les-radioamateurs/). Named bands are not exact frequency bounds. Argentina's LU6FLZ also has an [operator-authorized public gateway](https://sdr.lu7dko.ar/en/), but integration status and reuse permission for Pulse were not established; no gateway path spoofing or origin expansion.

## Further held leads (not included)
- [National Institute of Amateur Radio contributor VU2JOS](https://www.qsl.net/vu2jos/SDR.htm): VU24DX Kozhikode, India (HTTP :8901); endpoint retrieval unavailable. VU2CPL Bangalore :8901 appears in a separate ReceiverBook listing; other VU2CPL services use OpenWebRX. Require operator page/protocol verification.
- BU2FS Taipei, Taiwan: [third-party description](https://hamru.ru/o-radio/websdr/strany-azii/tajvan/7919-taipei) lists 2m, but no current individual operator page confirmed.
- CX1AAO Playa Hermosa, Uruguay: radio club link exists; current receiver state not established and third-party status shows limited access. Keep out of embedded list.
- ES4O Estonia: `https://es4o.erau.ee/` could not be retrieved.
- LU5DNP Argentina has conflicting classic WebSDR and newer NovaSDR listings; verify before adding. LU6PSG direct page timed out.
- LZ7AA Sofia and RepublicaOA6 alternate host now present OpenWebRX+ interfaces; do not pretend these use the classic WebSDR tuning contract.
- Chile, Australia, New Zealand, Africa and much of Asia have public SDR options but many use KiwiSDR/OpenWebRX/UberSDR. Only add classic WebSDR after protocol and operator confirmation. Do not restore KiwiSDR or assume unrelated protocols are compatible.

## Acceptance
Manually test a representative set using actual audio and receiver tuning in the packaged Windows application. Verify selection, frequency/mode, stop/hide/shutdown, error behavior, exact-origin and consent restrictions, and no auto-connection. Browser-only candidates may be promoted individually only after direct endpoint review and explicit transport checks. This is not evidence of new native audio playback or public release approval.
