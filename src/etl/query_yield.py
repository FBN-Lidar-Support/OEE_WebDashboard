import requests
import xml.etree.ElementTree as ET
import pandas as pd

def FIT_Query_Table():
    url = "https://service.fabrinet.co.th/FBNFITSService/FBNFITSServices.svc?wsdl"
    xml_soap = """<?xml version='1.0'?>
    <x:Envelope xmlns:x="http://schemas.xmlsoap.org/soap/envelope/" xmlns:tem='http://tempuri.org/'>
        <x:Header/>
        <x:Body>
            <tem:fn_Query_Table>
            <tem:project_id>729</tem:project_id>
            <tem:user_name>tech_ws</tem:user_name>
            <tem:user_password>kG7m@691</tem:user_password>
            <tem:model>-</tem:model>
            <tem:operation>-</tem:operation>
            <tem:revision>2.4</tem:revision>
            <tem:serial>-</tem:serial>
            <tem:parameters>Yield</tem:parameters>
            <tem:fsp>,</tem:fsp>
        </tem:fn_Query_Table>
        </x:Body>
    </x:Envelope>"""
    headers = {
        'Content-Type': 'text/xml; charset=UTF-8', 'SOAPAction': '"http://tempuri.org/IFBNFITSServices/fn_Query_Table"'
    }
    response = requests.request("POST", url, headers=headers, data=xml_soap)
    # print(response.text)
    aResult = xml_to_dataframe(response.text)
    return aResult

def xml_to_dataframe(xml_text: str) -> pd.DataFrame:
    root = ET.fromstring(xml_text.strip())
    data = []
    for row in root.findall(".//{*}RESULT"):
        operation_description = row.findtext("./{*}operation_description")
        # ข้าม RESULT ที่ไม่ใช่ข้อมูลแต่ละแถว
        if not operation_description:
            continue
        if ":" in operation_description:
            operation_id, operation_name = operation_description.split(":", 1)
        else:
            operation_id = ""
            operation_name = operation_description
        data.append({
            "model_type": row.findtext(
                "./{*}model_type",
                default=""
            ).strip(),
            "operation_id": operation_id.strip(),
            "operation_name": operation_name.strip(),
            "total": int(
                row.findtext("./{*}total", default="0")
            ),
            "pass": int(
                row.findtext("./{*}pass", default="0")
            ),
            "fail": int(
                row.findtext("./{*}Fail", default="0")
            ),
            "percentage": float(
                row.findtext("./{*}percentage", default="0")
            )
        })
    return pd.DataFrame(data)

def get_yield_yesterday():
    df = FIT_Query_Table()    
    # print(df.loc[df['model_type'] == "Main line"].to_string())
    # print("="*100)
    
    AB2B = df.loc[df['operation_id'].isin(['IN400', 'IN405', 'IN410', 'IN412', 'IN415', 'IN420', 'IN425'])]
    AA_FAS_SAS = df.loc[df['operation_id'].isin(['IN450', 'IN460', 'IN485', 'IN490', 'IN500'])]
    AA_TP = df.loc[df['operation_id'].isin(['IN510','IN520'])]
    IEOL_S = df.loc[df['operation_id'].isin(['FA210', 'FA220', 'FA230'])]
    IEOL_L = df.loc[df['operation_id'].isin(['FA235', 'FA240', 'FA250', 'FA255', 'FA260', 'FA270'])]
    
    AB2B_input_first_opn        = int(AB2B.iloc[0]["total"])
    AB2B_total_last_opn         = int(AB2B.iloc[-1]["total"])
    AB2B_pass_last_opn          = int(AB2B.iloc[-1]["pass"])
    
    AA_FAS_SAS_input_first_opn  = int(AA_FAS_SAS.iloc[0]["total"])
    AA_FAS_SAS_total_last_opn   = int(AA_FAS_SAS.iloc[-1]["total"])
    AA_FAS_SAS_pass_last_opn    = int(AA_FAS_SAS.iloc[-1]["pass"])
    
    AA_TP_input_first_opn       = int(AA_TP.iloc[0]["total"])
    AA_TP_total_last_opn        = int(AA_TP.iloc[-1]["total"])
    AA_TP_pass_last_opn         = int(AA_TP.iloc[-1]["pass"])
    
    EOL_S_input_first_opn         = int(IEOL_S.iloc[0]["total"])
    EOL_S_total_last_opn          = int(IEOL_S.iloc[-1]["total"])
    EOL_S_pass_last_opn           = int(IEOL_S.iloc[-1]["pass"])
    
    EOL_L_input_first_opn         = int(IEOL_L.iloc[0]["total"])
    EOL_L_total_last_opn          = int(IEOL_L.iloc[-1]["total"])
    EOL_L_pass_last_opn           = int(IEOL_L.iloc[-1]["pass"])
    
    return {
        "AB2B": {
            "input_first_opn":  AB2B_input_first_opn,
            "total_last_opn":   AB2B_total_last_opn,
            "pass_last_opn":    AB2B_pass_last_opn
        },
        "AA_FAS_SAS": {
            "input_first_opn":  AA_FAS_SAS_input_first_opn,
            "total_last_opn":   AA_FAS_SAS_total_last_opn,
            "pass_last_opn":    AA_FAS_SAS_pass_last_opn
        },
        "AA_TP": {
            "input_first_opn":  AA_TP_input_first_opn,
            "total_last_opn":   AA_TP_total_last_opn,
            "pass_last_opn":    AA_TP_pass_last_opn
        },
        "IEOL_SHORT": {
            "input_first_opn":  EOL_S_input_first_opn,
            "total_last_opn":   EOL_S_total_last_opn,
            "pass_last_opn":    EOL_S_pass_last_opn
        },
        "IEOL_LONG": {
            "input_first_opn":  EOL_L_input_first_opn,
            "total_last_opn":   EOL_L_total_last_opn,
            "pass_last_opn":    EOL_L_pass_last_opn,
        }
    }
    
# yield_machine = get_yield_yesterday()

# for MC in yield_machine.items():
#     print(MC)