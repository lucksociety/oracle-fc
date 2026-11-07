import json,subprocess
from oraclefc.market.best_bet import score_supports
from pathlib import Path

def test_every_market_and_js_parity():
    score={"home":4,"away":2}
    cases=[({"kind":"total","line":6.5,"over":True},False),({"kind":"total","line":6.5,"over":False},True),({"kind":"total","line":6,"over":True,"neg":True},False),({"kind":"1x2","res":"H"},True),({"kind":"1x2","res":"A"},False),({"kind":"1x2","res":"A","neg":True},True),({"kind":"btts"},True),({"kind":"btts","neg":True},False),({"kind":"team_total","team":"home","line":4.5,"over":True},False),({"kind":"spread","team":"away","hcp":2.5},True),({"kind":"spread","team":"away","hcp":2},False),({"kind":"exact","h":4,"a":2},True)]
    for spec,want in cases: assert score_supports(spec,score)==want
    js=Path(__file__).parents[1]/'web/bestbet.js'
    actual=json.loads(subprocess.check_output(['node','-e',"const B=require(process.argv[1]);let [cs,s]=JSON.parse(process.argv[2]);console.log(JSON.stringify(cs.map(([x])=>B.scoreSupports(x,s))))",str(js),json.dumps([cases,score])]))
    assert actual==[want for _,want in cases]
    assert not score_supports(cases[0][0],None)
