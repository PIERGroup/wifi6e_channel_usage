#!/usr/bin/env python3

import requests
import concurrent.futures
from dataclasses import dataclass, field

requests.packages.urllib3.disable_warnings()

# This is a class to store the ap data from the controllers.  This makes it easier to add more data later as we are asked for more data
@dataclass
class ArubaAP:
    name: str
    mac: str = field(default="")
    serial: str = field(default="")
    model: str = field(default="")
    primary: str = field(default="")
    secondary: str = field(default="")
    status: str = field(default="")
    ip: str = field(default="")
    flags: str = field(default="")
    group: str = field(default="")

# Class to store the API token per controller or conductor
@dataclass
class ArubaToken:
    wc: str
    uid: str
    csrf: str

# class to store radio information
@dataclass
class Radio:
    ap: str
    band: str
    model: str
    group: str
    channel: str

# Class to store the inventory of class instantiations for APs and API credentials
@dataclass
class ArubaInventory:
    aps: dict = field(default_factory=dict)
    api: dict = field(default_factory=dict)
    radios: dict = field(default_factory=dict)

def get_aruba_api_token(wc, username, password, inventory):
    r = requests.get(url="https://" + wc + ":4343/v1/api/login?username=" + username + "&password=" + password, verify=False)
    logindata = r.json()
    # store the api token in a dict to reference later
    tmp_token = ArubaToken(wc, logindata["_global_result"]["UIDARUBA"], logindata["_global_result"]["X-CSRF-Token"])
    inventory.api[wc] = tmp_token

def logout_aruba_api_token(wc, inventory):
    uid = inventory.api[wc].uid
    cookie = dict(SESSION=uid)
    response = requests.get(
        url="https://" + wc + ":4343/v1/api/logout?UIDARUBA=" + uid,
        data="",
        headers={},
        cookies=cookie,
        verify=False,
    )
    return response.json()

def aruba_show_command(wc, command, inventory):
    # generic show commands api query
    uid = inventory.api[wc].uid
    cookie = dict(SESSION=uid)
    response = requests.get(
        url="https://" + wc + ":4343/v1/configuration/showcommand?command=" + command + "&UIDARUBA=" + uid,
        data="",
        headers={},
        cookies=cookie,
        verify=False,
    )
    return response.json()

def get_radio_data(md, inventory):
    radio_data = aruba_show_command(md, "show ap radio-summary", inventory)
    for radio in radio_data["APs Radios information"]:
        if md==inventory.aps[radio['Name']].primary:
            if radio["Band"].startswith("6"):
                inventory.radios[f"{radio['Name']}"] = Radio(
                    band=radio["Band"],
                    ap=radio['Name'],
                    model=radio["AP Type"],
                    group=radio["Group"],
                    channel=radio["Mode"].split(":")[2],
            
                )

def get_aruba_db_md(wc, inventory):
    command = "show+ap+database+long"
    response = aruba_show_command(wc, command, inventory)
    # parse json response and update the class
    for ap in response["AP Database"]:
        if ap["Status"].startswith("Up"):
            if ap["Switch IP"] == wc:
                inventory.aps[ap["Name"]] = ArubaAP(
                    name=ap["Name"],
                    mac=ap["Wired MAC Address"],
                    ip=ap["IP Address"],
                    flags=ap["Flags"],
                    model=ap["AP Type"],
                    serial=ap["Serial #"],
                    primary=ap["Switch IP"],
                    secondary=ap["Standby IP"],
                    status=ap["Status"],
                    group=ap["Group"],
                )

def main():
    # update the username and the password
    username = "username"
    password = "password"
    # put in each of the primary mobility conductor IPs
    mobility_conductors = ["1.2.3.4","1.2.2.2"]
    wifi6e_80mhz_channels = [
        "133E",
        "53E",
        "117E",
        "149E",
        "165E",
        "181E",
        "213E",
        "37E",
        "101E",
        "69E",
        "197E",
        "85E",
        "21E"]
    # this will be auto populated with the mobility controllers
    mobility_controllers = []
    channel_data = {}
    inventory = ArubaInventory()

    # log into the mobility conductors
    with concurrent.futures.ThreadPoolExecutor() as executor:
        for mm in mobility_conductors:
            executor.submit(get_aruba_api_token, mm, username, password, inventory)
    # get the mobility controllers from the mobility conductors        
    for mm in mobility_conductors:
        response = aruba_show_command(mm, "show+switches+debug", inventory)
        for switch in response["All Switches"]:
            if switch["Type"] == "MD":
                mobility_controllers.append(switch["IP Address"])
    # log into the mobility controllers
    with concurrent.futures.ThreadPoolExecutor() as executor:
        for md in mobility_controllers:
            executor.submit(get_aruba_api_token, md, username, password, inventory)
    # get the AP data from the mobility controllers
    with concurrent.futures.ThreadPoolExecutor() as executor:
        for md in mobility_controllers:
            executor.submit(get_aruba_db_md, md, inventory)
    # get ap radio information for wifi 6e channels
    with concurrent.futures.ThreadPoolExecutor() as executor:
        for md in mobility_controllers:
            executor.submit(get_radio_data, md, inventory)
    # log out of the mobility conductors and controllers
    with concurrent.futures.ThreadPoolExecutor() as executor:
        for md in mobility_conductors:
            executor.submit(logout_aruba_api_token, md, inventory)
    with concurrent.futures.ThreadPoolExecutor() as executor:
        for md in mobility_controllers:
            executor.submit(logout_aruba_api_token, md, inventory)

    # compile the data, and only look for the 80mhz wide channels for 6e
    for radio in inventory.radios:
        if inventory.radios[radio].channel in wifi6e_80mhz_channels:
            channel_data.setdefault(inventory.radios[radio].channel, 0)
            channel_data[inventory.radios[radio].channel] += 1
            
    # print the data out as a csv for easy import into a spreadsheet
    for channel in channel_data:
        print(f"{channel},{channel_data[channel]}")
                

if __name__ == "__main__":
    main()
