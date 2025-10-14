import dash
import pandas as pd
from dash import dcc
from dash import html, Input, Output, State, callback, dash_table
import plotly.graph_objs as go

from gui.file_manager import FileManager

from logai.telemetry_parser import Telemetry2Parser
from logai.telemetry_parser import DML

telemetry_parser = Telemetry2Parser()
file_manager = FileManager()

def create_summary_layout(data=pd.DataFrame()):
    mac = telemetry_parser.get_telemetry_value(DML.MAC_ADDRESS)
    serial = telemetry_parser.get_telemetry_value(DML.SERIAL_NUMBER)
    sw_ver = telemetry_parser.get_telemetry_value(DML.SW_VERSION)
    hw_ver = telemetry_parser.get_telemetry_value(DML.HW_VERSION)
    model = telemetry_parser.get_telemetry_value(DML.MODEL_NAME)
    manuf = telemetry_parser.get_telemetry_value(DML.MANUFACTURER, index=1)

    # Summary content
    summary_layout = html.Div([
        html.P(f"MAC Address\t: {mac}"),
        html.P(f"Serial Number\t: {serial}"),
        html.P(f"Software Version\t: {sw_ver}"),
        html.P(f"Hardware Version\t: {hw_ver}"),
        html.P(f"Model Name\t: {model}"),
        html.P(f"Manufacturer\t: {manuf}"),
    ])
    return summary_layout

def create_status_layout(data=pd.DataFrame()):
    wan_type = telemetry_parser.get_telemetry_value(DML.WAN_MODE)
    radio1_en = telemetry_parser.get_telemetry_value(DML.RADIO1_EN)
    radio2_en = telemetry_parser.get_telemetry_value(DML.RADIO2_EN)
    ap1_en = telemetry_parser.get_telemetry_value(DML.AP1_EN)
    ap2_en = telemetry_parser.get_telemetry_value(DML.AP2_EN)
    airties = telemetry_parser.get_telemetry_value(DML.AIETIES_EDGE)
    # Summary content
    summary_layout = html.Div([
        html.P(f"WAN Mode\t: {wan_type}"),
        html.P(f"Airtes Enable Status\t: {airties}"),
        html.P(f"Radio 1 Enabled\t: {radio1_en}"),
        html.P(f"Radio 2 Enabled\t: {radio2_en}"),
        html.P(f"SSID 1 Enabled\t: {ap1_en}"),
        html.P(f"SSID 2 Enabled\t: {ap2_en}"),
    ])
    return summary_layout

def parse_size(value):
    if value is None: return None
    if isinstance(value, (int, float)): return float(value)
    value = value.strip()
    try:
        if value.lower().endswith("kb"):
            return float(value[:-2].strip())
        elif value.lower().endswith("m"):
            return float(value[:-1].strip()) * 1024
        return float(value)
    except:
        return None

def create_mem_graph_layout(data):
    # Chart content
    time = telemetry_parser.get_timestamp()

    mem_avail = telemetry_parser.get_telemetry_col(DML.MEM_AVAILABLE)
    free_mem = telemetry_parser.get_telemetry_col(DML.MEM_FREE)
   
    if time is None or mem_avail is None or free_mem is None:
        return dcc.Graph()
    
    mem_avail = mem_avail.apply(parse_size)
    free_mem = free_mem.apply(parse_size)

    chart = dcc.Graph(
        figure={
            "data": [
                go.Scatter(x=time, y=mem_avail, name="Available", mode="lines"),
                go.Scatter(x=time, y=free_mem, name="Free", mode="lines"),
            ],
            "layout": go.Layout(
                title="Memory Split",
                xaxis_title="Report Time",
                yaxis_title="Value",
                hovermode="x unified"
            )
        }
    )
    return chart

def create_cpu_graph_layout(data):
    # Chart content
    time = telemetry_parser.get_timestamp()

    cpu_usage = telemetry_parser.get_telemetry_col(DML.CPU_USAGE)
    cpu_temp = telemetry_parser.get_telemetry_col(DML.CPU_TEMP)
   
    if cpu_temp is None or cpu_temp is None:
        return dcc.Graph()

    chart = dcc.Graph(
        figure={
            "data": [
                go.Scatter(x=time, y=cpu_usage, name="CPU Usage", mode="lines"),
                go.Scatter(x=time, y=cpu_temp, name="CPU Temp", mode="lines"),
            ],
            "layout": go.Layout(
                title="CPU usage vs temp",
                xaxis_title="Report Time",
                yaxis_title="Value",
                hovermode="x unified"
            )
        }
    )
    return chart


def create_wan_graph_layout(data):
    # Chart content
    time = telemetry_parser.get_timestamp()

    byte_rcvd = telemetry_parser.get_telemetry_col(DML.WAN_BYTES_RCVD)
    byte_sent = telemetry_parser.get_telemetry_col(DML.WAN_BYTES_SENT)
    pkt_rcvd = telemetry_parser.get_telemetry_col(DML.WAN_PKT_RCVD)
    pkt_sent = telemetry_parser.get_telemetry_col(DML.WAN_PKT_SENT)
   
    if byte_rcvd is None or byte_sent is None or pkt_rcvd is None or pkt_sent is None:
        return dcc.Graph()

    chart = dcc.Graph(
        figure={
            "data": [
                go.Scatter(x=time, y=byte_sent, name="Bytes Sent", mode="lines"),
                go.Scatter(x=time, y=byte_rcvd, name="Bytes Received", mode="lines"),
                go.Scatter(x=time, y=pkt_rcvd, name="Packet Sent", mode="lines"),
                go.Scatter(x=time, y=pkt_sent, name="Packet Received", mode="lines"),
            ],
            "layout": go.Layout(
                title="WAN stats",
                xaxis_title="Report Time",
                yaxis_title="Value",
                hovermode="x unified"
            )
        }
    )
    return chart

def create_wan_graph_layout(data):
    # Chart content
    time = telemetry_parser.get_timestamp()

    byte_rcvd = telemetry_parser.get_telemetry_col(DML.WAN_BYTES_RCVD)
    byte_sent = telemetry_parser.get_telemetry_col(DML.WAN_BYTES_SENT)
    pkt_rcvd = telemetry_parser.get_telemetry_col(DML.WAN_PKT_RCVD)
    pkt_sent = telemetry_parser.get_telemetry_col(DML.WAN_PKT_SENT)
   
    if byte_rcvd is None or byte_sent is None or pkt_rcvd is None or pkt_sent is None:
        return dcc.Graph()

    chart = dcc.Graph(
        figure={
            "data": [
                go.Scatter(x=time, y=byte_sent, name="Bytes Sent", mode="lines"),
                go.Scatter(x=time, y=byte_rcvd, name="Bytes Received", mode="lines"),
                go.Scatter(x=time, y=pkt_rcvd, name="Packet Sent", mode="lines"),
                go.Scatter(x=time, y=pkt_sent, name="Packet Received", mode="lines"),
            ],
            "layout": go.Layout(
                title="WAN stats",
                xaxis_title="Report Time",
                yaxis_title="Value",
                hovermode="x unified"
            )
        }
    )
    return chart

def create_radio_stat_graph_layout(data):
    # Chart content
    time = telemetry_parser.get_timestamp()

    byte_rcvd = telemetry_parser.get_telemetry_col(DML.SSID1_BYTE_RCVD)
    byte_sent = telemetry_parser.get_telemetry_col(DML.SSID1_BYTE_SENT)
    pkt_rcvd = telemetry_parser.get_telemetry_col(DML.SSID1_PKT_RCVD)
    pkt_sent = telemetry_parser.get_telemetry_col(DML.SSID1_PKT_SENT)
    err_rcvd = telemetry_parser.get_telemetry_col(DML.SSID1_ERROR_RCVD)
    err_sent = telemetry_parser.get_telemetry_col(DML.SSID1_ERROR_SENT)
   
    if byte_rcvd is None or byte_sent is None or pkt_rcvd is None or pkt_sent is None:
        return dcc.Graph()

    if err_rcvd is None or err_sent is None:
        return dcc.Graph()
    
    chart = dcc.Graph(
        figure={
            "data": [
                go.Scatter(x=time, y=byte_sent, name="Bytes Sent", mode="lines"),
                go.Scatter(x=time, y=byte_rcvd, name="Bytes Received", mode="lines"),
                go.Scatter(x=time, y=pkt_rcvd, name="Packet Sent", mode="lines"),
                go.Scatter(x=time, y=pkt_sent, name="Packet Received", mode="lines"),
                go.Scatter(x=time, y=err_sent, name="Error Sent", mode="lines"),
                go.Scatter(x=time, y=err_rcvd, name="Error Received", mode="lines"),
            ],
            "layout": go.Layout(
                title="SSID 1 stats",
                xaxis_title="Report Time",
                yaxis_title="Value",
                hovermode="x unified"
            )
        }
    )
    return chart
'''
def create_process_table(data):
    df = telemetry_parser.extract_ccsp_mem_split_data()
    return dash_table.DataTable(
        id='process-table',
        columns=[{"name": col, "id": col} for col in df.columns],
        data=data,
        page_size=10,
        style_table={'overflowX': 'auto'},
        style_header={'fontWeight': 'bold'},
        style_cell={'textAlign': 'left'},
    )

# Callback to update table
@callback(
    Output("process-table", "children"),
    Input("process-select", "value"),
    [
        State("process-select", "value"),
    ],
)
def update_table(selected_process, sel):
    ctx = dash.callback_context
    if ctx.triggered:
        prop_id = ctx.triggered[0]["prop_id"].split(".")[0]
        
        if prop_id == "process-select":
            if len(selected_process) == 0:
                return dash_table.DataTable()
            
            df = telemetry_parser.extract_ccsp_mem_split_data()
            filtered_df = df[df['NAME'] == selected_process]
            #data = filtered_df.sort_values('TimeStamp').to_dict('records')
            columns = [{"name": col, "id": col} for col in df.columns]
            return dash_table.DataTable(
                id='process-table',
                columns=columns,
                data=filtered_df.sort_values('TimeStamp').to_dict('records'),
                page_size=10,
                style_table={'overflowX': 'auto'},
                style_header={'fontWeight': 'bold'},
                style_cell={'textAlign': 'left'},
                )

@callback(
    Output("dev-summary-card", "children"),
    Output("dev-status-card", "children"),
    Output("process-select", "options"),
    Output("process-select", "value"),
    #Output("cpu-chart-card", "children"),
    #Output("mem-chart-card", "children"),
    #Output("network-stat-chart-card", "children"),
    #Output("radio-stat-chart-card", "children"),
    Output("telemetry_exception_modal", "is_open"),
    Output("telemetry_exception_modal_content", "children"),
    [
        Input("telemetry-btn", "n_clicks"),
        Input("telemetry_exception_modal_close", "n_clicks"),
    ],
)
def click_run(
    btn_click, modal_close
):
    options = []
    ctx = dash.callback_context
    try:
        if ctx.triggered:
            prop_id = ctx.triggered[0]["prop_id"].split(".")[0]
            #print(prop_id)
            if prop_id == "telemetry-btn":
                file_manager = FileManager()
                #filename = "telemetry2_0"
                #config_json = file_manager.load_config(filename)
                #print(config_json, flush=True)
                telemetry_parser.extract_telemetry_reports()
                telemetry_parser.start_processing()
                data = telemetry_parser.get_telemetry_report()
                #cpu = create_cpu_graph_layout(data)
                summary = create_summary_layout(data)
                sts = create_status_layout(data)

                # Tables
                #ccsp_mem = create_ccsp_mem_split_table(data)
                #ccsp_mem = dash_table.DataTable()
                df = telemetry_parser.extract_ccsp_mem_split_data()
                #print([{'label': name, 'value': name} for name in df['NAME'].unique()])
                options = [{'label': name, 'value': name} for name in df['NAME'].unique()]
                value = df['NAME'].unique()[0]

                """
                mem_graph = create_mem_graph_layout(data)
                wan_stat = create_wan_graph_layout(data)
                radio_stat = create_radio_stat_graph_layout(data)
                """

                return summary, sts, options,value, False, ""

            elif prop_id == "pattern_exception_modal_close":
                print("model close")
                return html.Div([]),html.Div([]), options, "", False, ""
        else:
            print("else model close")
            return html.Div([]),html.Div([]),options, "", False, ""
    except Exception as error:
        print("else model close except")
        return html.Div([]),html.Div([]), options, "", True, str(error)
'''