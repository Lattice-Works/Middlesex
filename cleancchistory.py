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

# Select columns which are np.datetime64 and make  them into dates (dt.floor('d'))
cc_hist_date_columns = [k for (k,v) in clean_cc_hist.dtypes.items() if v.type == np.datetime64]

for col in cc_hist_date_columns:
    clean_cc_hist[col] = clean_cc_hist[col].dt.floor('d')

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