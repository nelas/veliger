import os, sys
sys.path.append('/home/nelas/cifonauta/weblarvae')
os.environ['DJANGO_SETTINGS_MODULE'] = 'settings'
import django.core.handlers.wsgi
application = django.core.handlers.wsgi.WSGIHandler()