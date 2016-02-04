import os
import sys
import pandas as pd
import xlrd
import requests
import re
from datetime import datetime
from uuid import UUID, uuid5
from bs4 import BeautifulSoup

from cdisutils.log import get_logger
from gdcdatamodel.models import File, Case

CLINICAL_NAMESPACE = UUID('b27e3043-1c1f-43c6-922f-1127905232b0')

ETHNICITY_MAP = {
    "Hispanic or Latino": "hispanic or latino",
    "Not Hispanic or Latinoispanic or Latino": "not hispanic or latino",
    "Not Hispanic or Latino": "not hispanic or latino",
    "Unknown": None,
    "Not Reported": None,
}

TITLE_STRINGS_TO_CHECK = [
    "gender",
    "race",
    "ethnicity",
    "vital_status",
    "age_at_diagnosis",
]


GENDER_TITLE_STRINGS = [
    "Gender",
    "gender",
    "Sex",
    "sex"
]

RACE_TITLE_STRINGS = [
    "Race",
    "race",
]

ETHNICITY_TITLE_STRINGS = [
    "Ethnicity",
    "ethnicity"
]

VITAL_STATUS_TITLE_STRINGS = [
    "Vital Status",
    "Vital status",
    "vital status",
    "VITAL STATUS"
]

# TODO: Get real strings here, these are placeholder
YEAR_TITLE_STRINGS = [
    "Year of Diagnosis",
    "year of diagnosis",
    "Year of diagnosis"
]

AGE_TITLE_STRINGS = [ 
    "Age at diagnosis (days)",
    "Age at Diagnosis in Days",
    "age at diagnosis (days)",
    "Age at Diagnosis in Days",
    "Dge at Diagnosis (Days)",
    "Age at diagnosis in days",
    "Age at enrollment (days)",
    "Age at Enrollment (days)"
    "Age at enrollment in days",
    "Age at Enrollment in Days"
]

DAYS_TO_DEATH_TITLE_STRINGS = [
    "Days to Death (Days)",
    "Days to death (days)",
    "days to death (days)",
    "Days to Death in Days",
    "Days to death in days",
    "days to death in days",
    "Time to Death (Days)",
    "Time to death (days)",
    "time to death (days)",
    "Time to Death in Days",
    "Time to death in days",
    "time to death in days",
]

# TODO: Get real strings here, these are placeholder
ICD_10_TITLE_STRINGS = [
    "ICD 10",
    "icd 10"
]

BARCODE_TITLE_STRINGS = [
    "TARGET Patient USI",
    "TARGET USI"
]

BASE_TITLE_STRING_TYPES = {
    "gender": GENDER_TITLE_STRINGS,
    "race" : RACE_TITLE_STRINGS,
    "ethnicity" : ETHNICITY_TITLE_STRINGS,
    "vital_status" : VITAL_STATUS_TITLE_STRINGS,
    "year_of_diagnosis" : YEAR_TITLE_STRINGS,
    "age_at_diagnosis" : AGE_TITLE_STRINGS,
    "days_to_death" : DAYS_TO_DEATH_TITLE_STRINGS,
    "icd_10" : ICD_10_TITLE_STRINGS
}


VITAL_STATUS_MAP = {
    "Alive": "alive",
    "Dead": "dead",
    "Unknown": None,
    "Lost to Follow-up": "lost to follow-up"
}

POSSIBLE_SHEET_NAMES = [
        "Final ", # the whitespace ("Final ") is not a typo, don't change it
        "Sheet1",
        "Clinical Data",
        "EXPORT",
]

BASE_URL = "https://target-data.nci.nih.gov"

ACCESS_LEVELS = [
    "Controlled",
    "Public"
]

# NB: projects commented out now that haven't been tested, but should
# be run eventually
PROJECTS_TO_SYNC = { 
    # "ALL-P1",
    # "ALL-P2",
    #"ALL/Phase_I" : "/Discovery/clinical/harmonized/",  # temp
    #"ALL/Phase_II" : "/Discovery/clinical/harmonized/", # temp
    "ALL" : "Discovery/clinical/harmonized/",
    "AML" : "Discovery/clinical/harmonized/",
    "AML-IF" : "Discovery/clinical/",
    "CCSK" : "Discovery/clinical/harmonized/",
    "NBL" : "Discovery/clinical/harmonized/",
    "OS" : "Discovery/clinical/",
    "RT" : "Discovery/clinical/harmonized/",
    "WT" : "Discovery/clinical/harmonized/"
}

ROW_CLASSES = [ "even", "odd" ]

log = get_logger("target_clinical_sync_{}".format(os.getpid()))


def normalize_gender(value):
    """Parse the gender into a canonical form."""
    return value.lower().strip()

def normalize_race(value):
    """Parse the race into a canonical form."""

    race = None
    if isinstance(value, basestring):
        if value.strip() == "Unknown":
            race = "not reported"
        else:
            race = value.lower().strip()

    return race

def normalize_ethnicity(value):
    """Parse the ethnicity into a canonical form."""
    return ETHNICITY_MAP[value.strip()]

def normalize_vital_status(value):
    """Parse vital status into a canonical form."""
    vital_status = None
    if isinstance(value, basestring):
        if value.strip() in VITAL_STATUS_MAP:
            vital_status = VITAL_STATUS_MAP[value.strip()]
        else:
            raise RuntimeError("Unknown vital status:", value)
    else:
       vital_status = VITAL_STATUS_MAP["Unknown"]

    return vital_status

def normalize_year_of_diagnosis(value):
    """Parse the year of diagnosis into a canonical form."""

    return value

def normalize_age_at_diagnosis(value):
    """Parse age at diagnosis into a canonical form."""

    return int(value)

def normalize_days_to_death(value):
    """Parse days to death into a canonical form."""

    return value

def normalize_icd_10(value):
    """Parse ICD 10 into a canonical form."""
    return value

CATEGORY_NORMALIZATIONS = {
    "gender": GENDER_TITLE_STRINGS,
    "race" : RACE_TITLE_STRINGS,
    "ethnicity" : ETHNICITY_TITLE_STRINGS,
    "vital_status" : VITAL_STATUS_TITLE_STRINGS,
    "year_of_diagnosis" : YEAR_TITLE_STRINGS,
    "age_at_diagnosis" : AGE_TITLE_STRINGS,
    "days_to_death" : DAYS_TO_DEATH_TITLE_STRINGS,
    "icd_10" : ICD_10_TITLE_STRINGS
}

NORMALIZE_MAP = {
    "gender": normalize_gender,
    "race" : normalize_race,
    "ethnicity" : normalize_ethnicity,
    "vital_status" : normalize_vital_status,
    "year_of_diagnosis" : normalize_year_of_diagnosis,
    "age_at_diagnosis" : normalize_age_at_diagnosis,
    "days_to_death" : normalize_days_to_death,
    "icd_10" : normalize_icd_10
}


def parse_header_strings(row, category):
    """Parse the header strings and best guess each."""

    header_str = None
    if category in BASE_TITLE_STRING_TYPES.keys():
        for entry in BASE_TITLE_STRING_TYPES[category]:
            if entry in row:
                header_str = entry
    else:
        log.warn("Unable to get header category for %s" % category)    
    if not header_str:
        log.warn("Unable to find header for category %s" % category)

    return header_str

def parse_row_into_props(row):
    """Parse a given row from a spreadsheet into a properties dict."""

    row_strings = {}
    output_dict = {}
    for key in BASE_TITLE_STRING_TYPES.keys():
        row_strings[key] = None
        output_dict[key] = None

    for string in TITLE_STRINGS_TO_CHECK:
        row_strings[string] = parse_header_strings(row, string)
        if not row_strings[string]:
            error_str = "Header string not found for %s" % string
            log.error(row)
            log.error(error_str)
            raise RuntimeError(error_str)
        else:
            output_dict[string] = NORMALIZE_MAP[string](row[row_strings[string]])

    #return {
    #    "gender": row["Gender"].lower().strip(),
    #    "race": parse_race(row["Race"]),
    #    "ethnicity": ETHNICITY_MAP[row["Ethnicity"].strip()],
    #    "vital_status": parse_vital_status(row[vital_status_row_string]),
    #    "year_of_diagnosis": None,
    #    "age_at_diagnosis": int(row[age_row_string]),
    #    "days_to_death": None,
    #    "icd_10": None,
    #}
    #print output_dict
    return output_dict

def match_date(string_to_check):
    """Match a version date found in a file name."""
    version = None
    version_match = re.search("([0-9]{8})", string_to_check)
    if version_match:
        version = datetime.strptime(version_match.group(1), "%Y%m%d").toordinal()

    if not version:
        version_match = re.search("([1-9]|1[012])[_ /.]([1-9]|[12][0-9]|3[01])[_ /.](19|20)\d\d",
            string_to_check
        )
        if version_match:
            version = datetime.strptime(version_match.group(0), "%m_%d_%Y").toordinal()

    return version

def process_tree(url, dcc_user, dcc_pass):
    """Walk the given url and recursively find all the spreadsheet links."""
    url_list = []
    r = requests.get(url, auth=(dcc_user, dcc_pass), verify=False)
    if r.status_code == 200:
        soup = BeautifulSoup(r.text, "lxml")
        file_table = soup.find('table', attrs={'id':'indexlist'})
        rows = file_table.find_all('tr')
        for row in rows:
            if row['class'][0] in ROW_CLASSES:
                image = row.find('img')
                if "DIR" not in image['alt']:
                    dir_data = {}
                    dir_data['dir_name'] = row.find('td', class_="indexcolname").get_text().strip()
                    link = row.find('a')
                    if ("xlsx" in link['href']) and ("Clinical" in link['href']):
                        dir_data['url'] = url + link['href']
                        url_list.append(dir_data)
    else:
        log.error("Unable to connect to %s, result %d - %s" % (
            url, r.status_code, r.reason
            )
        )
    return url_list

def find_clinical(args):
    """Find all the clinical spreadsheets for each project."""
    spreadsheet_urls = {}
    for project in args.projects:
        for access_level in ACCESS_LEVELS:
            url = "/".join([BASE_URL, access_level, project, PROJECTS_TO_SYNC[project]])
            spreadsheets = process_tree(url, args.dcc_user, args.dcc_pass)
            spreadsheet_urls[project] = spreadsheets
    
    return spreadsheet_urls

class TARGETClinicalSyncer(object):

    def __init__(self, project, url, graph=None, dcc_auth=None):
        """
        I am not sure of a good way to automatically determine the correct
        url for a project so for now you have to pass the url explicitly.
        """

        url_verified = False
        self.project = project
        self.log = get_logger("target_clinical_sync_{}_{}".format(self.project, os.getpid()))
        for level in ACCESS_LEVELS:
            url_str = "/".join([BASE_URL, level, project, "Discovery"])
            if url.startswith(url_str):
                url_verified = True
                break
            else:
                self.log.warning("URL incorrect")
                self.log.warning("Expected %s" % url_str)
                self.log.warning("We have  %s" % url)

        assert url_verified
        self.url = url
        self.version = match_date(url)
        if not self.version:
            raise RuntimeError("Could not extract version from url {}".format(url))
        self.graph = graph
        self.dcc_auth = dcc_auth


    def load_df(self):
        """Load the dataframe from a spreadsheet."""
        self.log.info("downloading clinical xlsx from target dcc")
        resp = requests.get(self.url, auth=self.dcc_auth)
        self.log.info("parsing clinical info into dataframe")
        book = xlrd.open_workbook(file_contents=resp.content)
        sheet_names = [sheet.name for sheet in book.sheets()]
        SHEET = None
        for sheet_str in sheet_names:
            if sheet_str in POSSIBLE_SHEET_NAMES:
                SHEET = sheet_str
                break

        #if "Final " in sheet_names:
        #    SHEET = "Final "
        #elif "Sheet1" in sheet_names:
        #    SHEET = "Sheet1"
        #elif "Clinical Data" in sheet_names:
        #    SHEET = "Clinical Data"
        #else:
        if not SHEET:
            error_str = "Unknown sheet names:", sheet_names
            self.log.error(error_str)
            raise RuntimeError(error_str)

        return pd.read_excel(book, engine="xlrd", sheetname=SHEET)

    def create_edge(self, label, src, dst):
        """Create a graph edge based upon the data."""
        maybe_edge = self.graph.edge_lookup(
            label=label,
            src_id=src.node_id,
            dst_id=dst.node_id,
        ).scalar()
        if not maybe_edge:
            self.graph.edge_insert(self.graph.get_PsqlEdge(
                label=label,
                src_id=src.node_id,
                dst_id=dst.node_id,
                src_label=src.label,
                dst_label=dst.label,
            ))

    def insert(self, df):
        """Insert the clinical data into the database."""
        self.log.info("loading clinical info into graph")
        with self.graph.session_scope():
            self.log.info("looking up the node corresponding to %s", self.url)
            try:
                clinical_file = self.graph.nodes(File)\
                                   .sysan({"source": "target_dcc",
                                   "url": self.url}).one()
            except:
                error_str = "Unable to find node in db with url %s" % self.url
                self.log.error(error_str)
                self.log.error("Have you done the DCC import for this project?")
                raise RuntimeError(error_str)
            else:
                self.log.info("found clinical file %s as %s", self.url, clinical_file)
                row_count = 0
                for _, row in df.iterrows():
                    # the .strip is necessary because sometimes there is a
                    # space after the name, e.g. 'TARGET-50-PAEAFB '
                    case = None
                    for column_title in BARCODE_TITLE_STRINGS:
                        case_barcode = None
                        if column_title in row:
                            # NB: some of the spreadsheets have blank rows, and
                            # the error condition is to strip on a non-string
                            # (it appears to default to int), so we have to use
                            # this as the check
                            if isinstance(row[column_title], basestring):
                                case_barcode = row[column_title].strip()
                                break
                            else:
                                if type(row[column_title]) == float:
                                    self.log.info("Empty row/int found at %d in %s" % (
                                        row_count, column_title
                                        )
                                    )
                                else:
                                    error_str = "Unrecognized type: %s at %d in %s" % (
                                        str(type(row[column_title])),
                                        row_count, column_title
                                        )
                                    self.log.error(error_str)
                                    raise RuntimeError(error_str)
                    if case_barcode:
                        self.log.info("looking up case %s", case_barcode)
                        case = self.graph.nodes(Case)\
                               .props({"submitter_id": case_barcode}).scalar()
                    if not case:
                        self.log.warning("couldn't find case %s, not inserting clinical data", case_barcode)
                        continue
                    self.log.info("found case %s as %s, inserting clinical info", case_barcode, case)
                    clinical = self.graph.node_merge(
                        node_id=str(uuid5(CLINICAL_NAMESPACE, case_barcode.encode('ascii'))),
                        label="clinical",
                        properties=parse_row_into_props(row),
                        system_annotations={
                            "url": self.url,
                            "version": self.version
                        }
                    )
                    self.log.info("inserted clinical info as %s, tieing to case", clinical)
                    self.create_edge("describes", clinical, case)
                    self.create_edge("describes", clinical_file, case)
                    row_count += 1

    def sync(self):
        """Main sync routine to sync the data."""
        df = self.load_df()
        self.insert(df)
