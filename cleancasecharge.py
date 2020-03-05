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

# booking query needed for join on SYSID to get PCP (person id)
booking_query = 'select "SYSID", "PCP" from booking;'
booking_df=pd.read_sql_query(booking_query, middlesex_engine)

case_charge_query = "select * from case_charge;"
case_charge_df=pd.read_sql_query(case_charge_query, middlesex_engine)

# Make a flight object from current yaml
fl2 = flight.Flight()
fl2.deserialize('/Users/nicholas/Clients/Middlesex/msocasecharge.yaml')
middlesex_cc_fd = fl2.schema
cc_flight_cols = list(fl2.get_all_columns())

# Create a dataframe which is a subset of the original table from columns included in the flight
clean_cc = case_charge_df[cc_flight_cols]

# Make OFFENSE_DATE into a datetime and coerce errors (make NaT) since datetime64 only goes to ~2250AD and some values are from 6201AD
clean_cc['OFFENSE_DATE'] = pd.to_datetime(clean_cc['OFFENSE_DATE'], errors = 'coerce')
    
# Strip all whitespace from object (string) columns and remove empty strings ('')
clean_cc = clean_cc.apply(lambda x: x.str.strip() if x.dtype == "object" else x)
clean_cc.replace('', np.nan, inplace=True)

# Join to booking on SYSID to get PCP (key for inmates)
clean_cc = clean_cc.set_index('SYSID').join(booking_df[['SYSID','PCP']].set_index('SYSID'))
clean_cc.reset_index()

# Select columns which are np.datetime64 and make  them into dates (dt.floor('d'))
cc_date_columns = [k for (k,v) in clean_cc.dtypes.items() if v.type == np.datetime64]

for col in cc_date_columns:
    clean_cc[col] = clean_cc[col].dt.floor('d')

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

make_assn_cols(clean_cc, middlesex_cc_fd)

# Take a sample and make a csv for sample integrations
clean_cc_sample = clean_cc.sample(1000)

clean_booking_sample.to_csv('cleancasechargesample.csv')