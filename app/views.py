from facebook import get_user_from_cookie, GraphAPI
from twilio.rest import TwilioRestClient
from datetime import datetime, timedelta
from flask import render_template, g, flash, session, url_for, redirect, request
from config import FB_APP_ID, FB_APP_NAME, FB_APP_SECRET, ACCOUNT_SID, AUTH_TOKEN, PHONE_NUMBER, SENDGRID_USER, SENDGRID_PW
from forms import ProfileForm, EventForm
from app import app, db
from app import models

import sendgrid

@app.route('/')
def index():
  """
  If logged in, return main.html. Otherwise return signin.html
  """
  if g.user:
    if g.first_time:
      g.first_time = False
      return redirect(url_for("profile"))
    user = models.User.query.get(g.user['id'])
    results = models.EventSubscription.query.filter_by(user=user)
    public = models.Event.query.filter_by(public=1).all()
    events = []
    for result in results:
      event = models.Event.query.get(result.event.id)
      if event.public==0:
        events.append(event)
    events = events + public
    print events
    events.sort(key=lambda x: x.happened_count)
      

    return render_template("table.html", events=events, app_id=FB_APP_ID, name=FB_APP_NAME)
  else:
    return render_template('fbsignin.html', app_id=FB_APP_ID, name=FB_APP_NAME)

@app.route('/profile', methods=['GET', 'POST'])
def profile():
  """
  Use this to let people change emails and phone numbers
  """
  if g.user is None:
    return redirect(url_for("index"))

  form = ProfileForm()
  if form.validate_on_submit():
    user = models.User.query.get(g.user['id'])
    user.email = form.email.data
    user.phone_number = form.phone_number.data
    print form.email.data
    print form.phone_number.data
    g.user['email'] = form.email.data
    g.user['phone_number'] = form.phone_number.data
    db.session.add(user)
    db.session.commit()
    flash('Your changes have been saved')
  return render_template("profile.html", app_id=FB_APP_ID, name=FB_APP_NAME, user = g.user, form=form)

@app.route('/add_event', methods=['GET', 'POST'])
def add_event():
  if g.user is None:
    return redirect(url_for("index"))

  form = EventForm()
  if form.validate_on_submit():
    what = form.what.data
    where = form.where.data
    length = form.length.data
    wait_time = form.wait_time.data
    pre_delay = form.pre_delay.data
    required_people = form.required_people.data
    description = form.description.data
    if form.public.data:
      public = 1
    else:
      public = 0
    event = models.Event(what=what, where=where, length=length, wait_time=wait_time, pre_delay=pre_delay, required_people=required_people, description=description, public=public)
    db.session.add(event)
    db.session.commit()
    user = models.User.query.get(g.user['id'])
    event_req = models.EventSubscription(user=user, event=event)
    db.session.add(event_req)
    db.session.commit()
    flash("Event successfully created")
    return redirect(url_for("event", id=event.id))
  return render_template("add_event.html", app_id=FB_APP_ID, name=FB_APP_NAME, user = g.user, form=form) 

@app.route('/event/<int:id>')
def event(id):
  if id is None:
    return redirect(url_for('index'))
  event = models.Event.query.get(id)
  return render_template("event.html", app_id=FB_APP_ID, name=FB_APP_NAME, event=event)
@app.route('/logout')
def logout():
  """Log out the user from the application.

  Log out the user from the application by removing them from the
  session.  Note: this does not log the user out of Facebook - this is done
  by the JavaScript SDK.
  """
  session.pop('user', None)
  return redirect(url_for('index'))

@app.route('/attend/<int:event_id>')
def attend(event_id):
  if g.user is None:
    return redirect(url_for("index"))

  event = models.Event.query.get(event_id)
  user = models.User.query.get(g.user['id'])
  updated_sub = models.EventSubscription.query.filter_by(event=event, user=user).first()
  updated_sub.signups += 1
  db.session.add(updated_sub)
  db.session.commit()

  now = datetime.utcnow()
  past = now-timedelta(minutes=event.wait_time)
  results = models.EventSubscription.query.filter_by(event=event).filter(models.EventSubscription.updated >= past).filter(models.EventSubscription.signups >= 1).all()
  if len(results) >= event.required_people:
    if event.happened_count is None:
      event.happened_count = 0
    event.happened_count += 1
    db.session.add(event)
    db.session.commit()
    for result in results:
      body = event.what+ " will start at "+event.where+" in "+str(event.pre_delay)+" minutes!"
      if result.user.phone_number:
        "WHAT start at WHERE in WHEN minute!"
        client = TwilioRestClient(ACCOUNT_SID, AUTH_TOKEN)
        message = client.messages.create(to=result.user.phone_number, from_=PHONE_NUMBER, body=body)

      if result.user.email:
        sg = sendgrid.SendGridClient(SENDGRID_USER, SENDGRID_PW)

        message = sendgrid.Mail()
        to = result.user.name + " <"+result.user.email+">"
        message.add_to(to)
        message.set_subject("Event starting soon!")
        message.set_html(body)
        message.set_text(body)
        message.set_from('Together App <no-reply@smerz.io>')
        status, msg = sg.send(message)

  return 'OK'

@app.route('/add_to_event/<int:event_id>/<int:user_id>')
def add_to_event(event_id, user_id):
  user = models.User.query.get(user_id)
  event = models.Event.query.get(event_id)
  event_req = models.EventSubscription(user=user, event=event)
  db.session.add(event_req)
  db.session.commit()

  return 'OK'


@app.before_request
def get_current_user():
  """Set g.user to the currently logged in user.

  Called before each request, get_current_user sets the global g.user
  variable to the currently logged in user.  A currently logged in user is
  determined by seeing if it exists in Flask's session dictionary.

  If it is the first time the user is logging into this application it will
  create the user and insert it into the database.  If the user is not logged
  in, None will be set to g.user.
  """

  # Set the user in the session dictionary as a global g.user and bail out
  # of this function early.
  g.first_time = False
  g.user = None
  if session.get('user'):
    g.user = session.get('user')
    return


  # Attempt to get the short term access token for the current user.
  result = get_user_from_cookie(cookies=request.cookies, app_id=FB_APP_ID,
                                app_secret=FB_APP_SECRET)

  # If there is no result, we assume the user is not logged in.
  if result:
    # Check to see if this user is already in our database.
    user = models.User.query.filter(models.User.id == result['uid']).first()

    if not user:
      # Not an existing user so get info
      graph = GraphAPI(result['access_token'])
      profile = graph.get_object('me')

      # Create the user and insert it into the database
      user = models.User(id=str(profile['id']), name=profile['name'],
                  profile_url=profile['link'],
                  access_token=result['access_token'])
      db.session.add(user)
      g.first_time = True
    elif user.access_token != result['access_token']:
      # If an existing user, update the access token
      user.access_token = result['access_token']

    # Add the user to the current session
    session['user'] = dict(name=user.name, profile_url=user.profile_url,
                           id=user.id, access_token=user.access_token,
                           email=user.email, phone_number=user.phone_number)

  # Commit changes to the database and set the user as a global g.user
  db.session.commit()
  g.user = session.get('user', None)
