import json
from backend.quant_engine import QuantEngine
from backend.audit_ledger import CryptoAuditLedger

qe = QuantEngine(bankroll=1000.0, default_tier='C')

markets = [
    {
        'match': 'Fiji vs Islas Salomón',
        'sport': 'Fútbol Internacional',
        'time': '18/09 01:00 CDMX',
        'home': 'Fiji',
        'away': 'Islas Salomón',
        'odds_decimal': {'1': 1.78, 'X': 3.50, '2': 4.25}, # -128, +250, +325
        'tier': 'C'
    },
    {
        'match': 'Filipinas U23 vs Vietnam U23',
        'sport': 'Juegos Asiáticos',
        'time': '18/09 00:30 CDMX',
        'home': 'Filipinas U23',
        'away': 'Vietnam U23',
        'odds_decimal': {'1': 9.00, 'X': 5.00, '2': 1.25}, # +800, +400, -400
        'tier': 'C'
    },
    {
        'match': 'Changchun Xidu vs Guangdong Mingtu',
        'sport': 'China League 2',
        'time': '18/09 02:00 CDMX',
        'home': 'Changchun Xidu',
        'away': 'Guangdong Mingtu',
        'odds_decimal': {'1': 2.54, 'X': 2.75, '2': 3.00}, # +154, +175, +200
        'tier': 'C'
    },
    {
        'match': 'Rizhao Yuqi vs Wenzhou Professional FC',
        'sport': 'China League 2',
        'time': '18/09 02:00 CDMX',
        'home': 'Rizhao Yuqi',
        'away': 'Wenzhou Professional FC',
        'odds_decimal': {'1': 2.00, 'X': 2.90, '2': 4.00}, # +100, +190, +300
        'tier': 'C'
    },
    {
        'match': 'Brentford vs Chelsea',
        'sport': 'Premier League',
        'time': '18/09 13:00 CDMX',
        'home': 'Brentford',
        'away': 'Chelsea',
        'odds_decimal': {'1': 2.66, 'X': 3.75, '2': 2.45}, # +166, +275, +145
        'tier': 'A'
    },
    {
        'match': 'Juárez vs Tigres UANL',
        'sport': 'Liga MX',
        'time': '18/09 21:00 CDMX',
        'home': 'Juárez',
        'away': 'Tigres UANL',
        'odds_decimal': {'1': 4.75, 'X': 3.80, '2': 1.73}, # +375, +280, -137
        'tier': 'A'
    }
]

print('=' * 70)
print('QUANT ENGINE INSTITUCIONAL — EVALUACION PLAYDOIT')
print('=' * 70)

for m in markets:
    res = qe.evaluate_3way_market(
        event_name=m['match'],
        odds=m['odds_decimal'],
        tier=m['tier']
    )
    print('Match:', m['match'], '|', m['time'], '| Tier:', m['tier'])
    print('  Vig (Overround):', f\"{res['overround_pct']:.2f}%\")
    print('  Fair Probs:', res['fair_probabilities'])
    print('  Action:', res['action'], '| Details:', res.get('recommendation', res.get('reason', '')))
    print('-' * 70)
