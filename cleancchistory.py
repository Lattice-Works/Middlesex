import sqlalchemy
import pandas as pd
import numpy as np
import yaml
from flighttools import flight

file = "***"
with open(file) as stream:
    mapper = yaml.safe_load(stream)
    creds = mapper['hikariConfigs']['middlesex']

db_name = creds['dbname']
usr_name = creds['username']
db_password = creds['password']

middlesex_engine = sqlalchemy.create_engine(f'postgresql://{usr_name}:{db_password}@atlas.openlattice.com:30001/{db_name}',connect_args={'sslmode':'require'})

cc_history_query = "select * from case_charge_history;"
cc_history_df=pd.read_sql_query(cc_history_query, middlesex_engine)

# Make a flight object from current yaml
fl = flight.Flight()
fl.deserialize('/Users/nicholas/Clients/Middlesex/msocchistory.yaml')
middlesex_cc_hist_fd = fl.schema
cc_hist_cols = list(fl.get_all_columns())

# Create a dataframe which is a subset of the original table from columns included in the flight
clean_cc_hist_hist = cc_history_df[cc_hist_cols]
    
# Strip all whitespace from object (string) columns and remove empty strings ('')
clean_cc_hist = clean_cc_hist.apply(lambda x: x.str.strip() if x.dtype == "object" else x)
clean_cc_hist.replace('', np.nan, inplace=True)

# Prepare dates for SQL
# First select those which need to be dates on backend and add to date_columns
# Then select those which are np.datetime64 in pandas (and possibly others) and localize
date_columns = ['DNA_SAMPLE_DATE','DISPOSITION_DATE']

for col in date_columns:
   clean_cc_hist[col] = clean_cc_hist[col].dt.strftime('%Y-%m-%d')

datetime_columns = [k for (k,v) in clean_cc_hist.dtypes.items() if v.type == np.datetime64    ]

for col in datetime_columns:
    clean_cc_hist[col] = pd.to_datetime(clean_cc_hist[col], errors='coerce').dt.tz_localiz    e("America/New_York")


# Functions to make association hash and make columns from those
def make_assn_hash(df, col1, col2, name):
    combined_cols = df[col1].astype(str) + df[col2].astype(str)
    assn_hash = combined_cols.apply(lambda x: hash(x+name))
    return assn_hash

def make_assn_cols(df, fd):
    for k, v in fd['associationDefinitions'].items():
        col_string = f"assn_{k}"
        src, dst = v['src'], v['dst']
        srccol = fd['entityDefinitions'][src]['properties'][0]['column']
        dstcol = fd['entityDefinitions'][dst]['properties'][0]['column']
        df[col_string] = make_assn_hash(df, srccol, dstcol, k)

make_assn_cols(clean_cc_hist, middlesex_cc_hist_fd)

# Take a sample and make a csv for sample integrations
clean_cc_hist_sample = clean_cc_hist.sample(1000)

clean_cc_hist_sample.to_csv('cleancchistsample.csv')