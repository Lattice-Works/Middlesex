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

booking_query = "select * from booking;"
booking_df=pd.read_sql_query(booking_query, middlesex_engine)

# Make a flight object from current yaml
fl = flight.Flight()
fl.deserialize('/Users/nicholas/Clients/Middlesex/msobooking.yaml')
middlesex_booking_fd = fl.schema
flight_cols = list(fl.get_all_columns())

# Create a dataframe which is a subset of the original table from columns included in the flight
clean_booking = booking_df[flight_cols]

# Strip all whitespace from object (string) columns, and remove all blank strings ('')
clean_booking = clean_booking.apply(lambda x: x.str.strip() if x.dtype == "object" else x)
clean_booking.replace('', np.nan, inplace=True)

# Make float columns to int to fit with the desired datatypes on prod
clean_booking['SERVED'] = clean_booking['SERVED'].astype('Int64')
clean_booking['AGE'] = clean_booking['AGE'].astype('Int64')
clean_booking['SENTENCED_AS_ADULT'] = clean_booking['SENTENCED_AS_ADULT'].map({'Y': 1, 'N': 0}).astype('Int64')

# Map SEX values to new values
clean_booking['SEX'] = clean_booking['SEX'].map({'M': "Male", "m": "Male", 'F': "Female", "C": "Unknown", "B": "Unknown", "H": "Unknown", "N": "Unknown", "]":"Unknown"})

# Set ambiguous values in RACE to Unknown and set W-White B-Black
clean_booking.loc[clean_booking['RACE'].isin(['H','U','D1','D3','D2','Z','D4','D7','AS','CV','AM']), 'RACE'] = 'Unknown'
clean_booking['RACE'] =clean_booking['RACE'].map({"W": "White", "B":"Black","A":"Asian", "Unknown":"Unknown"})

# Map Hispanic to Standard Values
clean_booking['HISPANIC'] = clean_booking['HISPANIC'].map({"Y":"Hispanic", "N":"Non-Hispanic"})

# Add value for datasource
clean_booking['DATASOURCE'] = "Middlesex County Jail"

# Officer Roles
clean_booking.loc[clean_booking['IDOFF'].notna(), 'ROLE'] = 'Officer'

clean_booking.loc[clean_booking['DNA_SAMPLE_OFFICER'].notna(), 'ROLE'] = 'Officer'
clean_booking.loc[clean_booking['DNA_SAMPLE_OFFICER'].notna(), 'DNA_ROLE_DESCRIPTION'] = 'DNA'

clean_booking.loc[clean_booking['COMOFF'].notna(), 'ROLE'] = 'Officer'
clean_booking.loc[clean_booking['COMOFF'].notna(), 'COM_ROLE_DESCRIPTION'] = 'Committing'

clean_booking.loc[clean_booking['RELOFF'].notna(), 'ROLE'] = 'Officer'
clean_booking.loc[clean_booking['RELOFF'].notna(), 'REL_ROLE_DESCRIPTION'] = 'Releasing'

# Prepare dates for SQL
# First select those which need to be dates on backend and add to date_columns
# Then select those which are np.datetime64 in pandas (and possibly others) and localize
date_columns = ['BIRTH','DNA_SAMPLE_DATE']

for col in date_columns:
    clean_booking[col] = clean_booking[col].dt.strftime('%Y-%m-%d')

datetime_columns = [k for (k,v) in clean_booking.dtypes.items() if v.type == np.datetime64]

for col in datetime_columns:
    clean_booking[col] = pd.to_datetime(clean_booking[col], errors='coerce').dt.tz_localize("America/New_York")


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

make_assn_cols(clean_booking, middlesex_booking_fd)

# Take a sample and make a csv for sample integrations
clean_booking_sample = clean_booking.sample(1000)

clean_booking_sample.to_csv('cleanbookingsample.csv')
