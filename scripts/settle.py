#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pandas as pd
from lexbet.data import connect, settle_open_picks
ROOT=Path(__file__).resolve().parents[1]; conn=connect(ROOT/'data/lexbet.sqlite')
frame=pd.read_sql_query('select * from matches where home_goals is not null and away_goals is not null',conn)
print(f'settled {settle_open_picks(conn, frame)} paper picks')
