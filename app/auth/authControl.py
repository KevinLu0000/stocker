from flask import (
    request, make_response, jsonify,
    redirect, session, current_app
)
from flask_login import (
    login_user, logout_user,
    login_required, current_user
)
from . import auth
from google.oauth2 import id_token
from google.auth.transport import requests as grequests
from ..database_setup import User
from .. import db
from datetime import timedelta
import json
import requests


@auth.route('/login', methods=['POST'])
def login():
    store_id_token = session.get('token')
    store_user_id = current_user.get_id()
    if store_id_token is not None and store_user_id is not None:
        response = make_response(
            json.dumps(
                {'res': 'Current user is already connected'}),200)
        print('Current user is already connected.')
        response.headers['Content-Type'] = 'application/json'
        return response

    try:
        code = request.get_json()
        if code['external_type']=='google':
            # Specify the CLIENT_ID of the app that accesses the backend:
            CLIENT_ID = current_app.config[
                'CLIENT_SECRET']['google']['CLIENT_ID']
            userInfo = id_token.verify_oauth2_token(
               code['token'],
               grequests.Request(),
               CLIENT_ID
            )

            # Or, if multiple clients access the backend server:
            # idinfo = id_token.verify_oauth2_token(token, requests.Request())
            # if idinfo['aud'] not in [CLIENT_ID_1, CLIENT_ID_2, CLIENT_ID_3]:
            #     raise ValueError('Could not verify audience.')
            if userInfo['iss'] not in [
                    'accounts.google.com', 'https://accounts.google.com']:
                raise ValueError('Wrong issuer.')

            if userInfo['aud'] != CLIENT_ID:
                res = make_response(
                    "Token's client ID does not match app's",401)
                res.headers['Content-Type'] = 'application/json'
                return res

            external_id = userInfo['sub']
        elif code['external_type']=='facebook':

            app_id = current_app.config[
                'CLIENT_SECRET']['facebook']['app_id']
            app_secret = current_app.config[
                'CLIENT_SECRET']['facebook']['app_secret']

            url = "https://graph.facebook.com/oauth/access_token"
            my_data = {
                "client_id": app_id,
                "client_secret": app_secret,
                "fb_exchange_token": code['token'],
                "redirect_uri": "http://localhost:5000",
                "grant_type": "fb_exchange_token"
            }
            payload = requests.post(url, data=my_data)
            if payload.status_code != 200:
                return make_response(json.dumps(payload.json()['error']), 400)
            print(payload.json())
            token = payload.json()['access_token']

            personalUrl = 'https://graph.facebook.com/v7.0/me?access_token={}&fields=name,id,email'\
            .format((token))
            picUrl = 'https://graph.facebook.com/v7.0/me/picture?access_token=%s&redirect=0&height=200&width=200'\
            % token

            userInfo = requests.get(personalUrl).json()
            pictureData = requests.get(picUrl).json()
            userInfo['profile_pic'] = pictureData['data']['url']

            external_id = userInfo['id']
    except Exception as fx:
        print(fx)
        res = make_response(
            json.dumps(
                'Failed to upgrade the authorization code'), 401)
        res.headers['Content-Type'] = 'application/json'
        return res

    userId = getUserID(external_id, code['external_type'])
    if(userId == None):
        userId = createUser(userInfo, code['external_type'])

    user = getUserInfo(userId)

    session['token'] = code['token']
    if user.is_active:
        login_user(user=user, remember=True, duration=timedelta(days=1))
    else:
        res = make_response(
            json.dumps(
                'Account is not active'), 403)
        res.headers['Content-Type'] = 'application/json'
        return res
    return json.dumps({'isAuthenticated': True})


@auth.route("/logout")
@login_required
def logout():
    del session['token']
    logout_user()
    return json.dumps({'isAuthenticated': False})


def createUser(personalData, external_type):
    newUser = User()

    newUser['external_type'] = external_type
    if external_type == 'google':
        newUser['username'] = personalData['name']
        newUser['external_id'] = personalData['sub']
        newUser['email'] = personalData['email']
        newUser['profile_pic'] = personalData['picture']
    elif external_type == 'facebook':
        newUser['username'] = personalData['name']
        newUser['external_id'] = personalData['id']
        newUser['email'] = personalData['email']
        newUser['profile_pic'] = personalData['profile_pic']
    newUser['authenticate'] = True
    newUser['active'] = False

    try:
        db.session.add(newUser)
        db.session.commit()
    except:
        db.session.rollback()
        print("fail create User: {}".format(personalData.name))
        return None
    userId = getUserID(newUser['external_id'], external_type)
    return userId


def getUserInfo(user_id):
    user = db.session.query(User).filter_by(id=user_id).one()
    return user


def getUserID(external_id, external_type):
    try:
        user = db.session.query(User).filter_by(
            external_id=external_id).filter_by(
                external_type=external_type).one()
        return user.id
    except:
        return None
