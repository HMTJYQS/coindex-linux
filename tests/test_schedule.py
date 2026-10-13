import datetime as dt
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'backend'))
from store import Store
from schedule import ZONE,automatic_state,day_state,normalize_calendar,refresh_calendars,finish_workday,off_duty_state,refresh_needed


def stamp(date):
    return dt.datetime.fromisoformat(date).replace(tzinfo=ZONE).timestamp()


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(self.tmp.name)
        self.raw=json.loads((pathlib.Path(__file__).parent/'fixtures/holidays-2026.json').read_text())
        self.calendar=normalize_calendar(self.raw,2026)
        self.calendar['updated_at']=stamp('2026-10-09T08:00')
        self.store.put_meta('calendar_2026',self.calendar)

    def tearDown(self):
        self.store.db.close()
        self.tmp.cleanup()

    def test_holidays_and_adjusted_weekends_override_weekday(self):
        self.assertFalse(automatic_state(self.store,stamp('2026-10-01T10:00'))['due'])
        saturday=automatic_state(self.store,stamp('2026-10-10T10:00'))
        self.assertTrue(saturday['due'])
        self.assertIn('调休补班',saturday['day_label'])
        sunday=automatic_state(self.store,stamp('2026-10-11T10:00'))
        self.assertFalse(sunday['due'])
        self.assertEqual(sunday['next_at'],stamp('2026-10-12T00:00'))

    def test_working_hours_include_opening_and_exclude_closing(self):
        self.store.save_settings({'work_hours_enabled':True})
        before=automatic_state(self.store,stamp('2026-10-09T08:59'))
        self.assertFalse(before['due'])
        self.assertEqual(before['next_at'],stamp('2026-10-09T09:00'))
        self.assertTrue(automatic_state(self.store,stamp('2026-10-09T09:00'))['due'])
        after=automatic_state(self.store,stamp('2026-10-09T18:00'))
        self.assertFalse(after['due'])
        self.assertEqual(after['next_at'],stamp('2026-10-10T09:00'))

    def test_thirty_minute_cadence_survives_restart_and_rolls_into_next_window(self):
        self.store.put_meta('last_check',stamp('2026-10-09T10:00'))
        result=automatic_state(self.store,stamp('2026-10-09T10:01'))
        self.assertFalse(result['due'])
        self.assertEqual(result['next_at'],stamp('2026-10-09T10:30'))
        self.store.db.close();self.store=Store(self.tmp.name)
        self.assertEqual(automatic_state(self.store,stamp('2026-10-09T10:02'))['next_at'],result['next_at'])
        self.store.save_settings({'work_hours_enabled':True})
        self.store.put_meta('last_check',stamp('2026-10-09T17:50'))
        self.assertEqual(automatic_state(self.store,stamp('2026-10-09T17:55'))['next_at'],stamp('2026-10-10T09:00'))

    def test_overnight_window_uses_starting_workday(self):
        self.store.save_settings({'work_hours_enabled':True,'work_start_minutes':1320,'work_end_minutes':360})
        self.assertTrue(automatic_state(self.store,stamp('2026-10-17T03:00'))['due'])
        self.assertFalse(automatic_state(self.store,stamp('2026-10-18T03:00'))['due'])

    def test_calendar_fetch_is_cached_and_offline_refresh_preserves_adjustments(self):
        now=stamp('2026-10-10T09:00')
        with patch('schedule.fetch_calendar',return_value=normalize_calendar(self.raw,2026)) as fetch:
            refresh_calendars(self.store,True,now)
            refresh_calendars(self.store,False,now+60)
            fetch.assert_called_once_with(2026)
        cached=self.store.meta('calendar_2026')
        with patch('schedule.fetch_calendar',side_effect=RuntimeError('offline')) as fetch:
            refresh_calendars(self.store,False,now+90000)
            refresh_calendars(self.store,False,now+90001)
            fetch.assert_called_once()
        self.assertEqual(self.store.meta('calendar_2026'),cached)
        self.assertIn('offline',self.store.meta('calendar_error_2026'))
        self.assertTrue(automatic_state(self.store,now)['due'])

    def test_missing_or_unpublished_calendar_does_not_guess_workdays(self):
        with self.store.db: self.store.db.execute("DELETE FROM meta WHERE key='calendar_2026'")
        result=automatic_state(self.store,stamp('2026-10-09T10:00'))
        self.assertFalse(result['due'])
        self.assertIsNone(result['next_at'])
        with self.assertRaisesRegex(ValueError,'尚未发布'):
            normalize_calendar({'year':2027,'papers':[],'days':[]},2027)
        self.store.save_settings({'workdays_only':False})
        self.assertTrue(automatic_state(self.store,stamp('2026-10-11T10:00'))['due'])

    def test_next_year_adjustments_can_override_december_dates(self):
        upcoming={'year':2027,'days':{'2026-12-31':{'off':True,'name':'元旦'}},'papers':['https://www.gov.cn/example']}
        self.assertFalse(day_state(dt.date(2026,12,31),self.store.settings(),{2026:self.calendar,2027:upcoming})[0])

    def test_calendar_timezone_is_beijing_even_when_utc_day_is_different(self):
        now=dt.datetime(2026,10,9,23,0,tzinfo=dt.timezone.utc).timestamp()
        self.assertIn('调休补班',automatic_state(self.store,now)['day_label'])
        self.assertTrue(automatic_state(self.store,now)['due'])

    def test_equal_work_hours_are_rejected_without_overwriting_settings(self):
        original=self.store.settings()
        with self.assertRaises(ValueError):
            self.store.save_settings({'work_hours_enabled':True,'work_start_minutes':600,'work_end_minutes':600})
        self.assertEqual(self.store.settings(),original)

    def test_off_duty_blocks_until_next_day_start_and_recovers_at_exact_boundary(self):
        self.store.save_settings({'work_hours_enabled':True,'work_start_minutes':600,'work_end_minutes':1380})
        settings=self.store.settings()
        until=finish_workday(self.store,stamp('2026-10-09T17:00'))
        self.assertEqual(until,stamp('2026-10-10T10:00'))
        for now in ('2026-10-09T18:00','2026-10-10T09:59:59'):
            result=automatic_state(self.store,stamp(now))
            self.assertTrue(result['off_duty']);self.assertFalse(result['due'])
            self.assertEqual(result['next_at'],until)
        result=automatic_state(self.store,until)
        self.assertFalse(result['off_duty']);self.assertTrue(result['due'])
        self.assertEqual(self.store.settings(),settings)

    def test_off_duty_survives_restart_and_repeat_click_does_not_extend(self):
        self.store.save_settings({'work_hours_enabled':True,'work_start_minutes':600})
        until=finish_workday(self.store,stamp('2026-10-09T17:00'))
        self.store.db.close();self.store=Store(self.tmp.name)
        self.assertTrue(off_duty_state(self.store,stamp('2026-10-10T08:00'))['off_duty'])
        self.assertEqual(finish_workday(self.store,stamp('2026-10-10T08:00')),until)

    def test_off_duty_expiry_does_not_bypass_weekends(self):
        self.store.save_settings({'work_hours_enabled':True,'work_start_minutes':600})
        until=finish_workday(self.store,stamp('2026-10-10T17:00'))
        result=automatic_state(self.store,until)
        self.assertEqual(until,stamp('2026-10-11T10:00'))
        self.assertFalse(result['off_duty']);self.assertFalse(result['due'])
        self.assertEqual(result['next_at'],stamp('2026-10-12T10:00'))

    def test_all_day_uses_midnight_across_year_and_keeps_beijing_timezone(self):
        self.store.save_settings({'workdays_only':False,'work_hours_enabled':False})
        until=finish_workday(self.store,stamp('2026-12-31T23:59'))
        self.assertEqual(until,stamp('2027-01-01T00:00'))
        self.assertFalse(automatic_state(self.store,until-1)['due'])
        self.assertTrue(automatic_state(self.store,until)['due'])
        # 23:00 UTC is already the following morning in Beijing.
        utc=dt.datetime(2026,10,9,23,0,tzinfo=dt.timezone.utc).timestamp()
        self.store.put_meta('off_duty_until',0)
        self.assertEqual(finish_workday(self.store,utc),stamp('2026-10-11T00:00'))

    def test_overnight_shift_still_waits_for_next_calendar_day_start(self):
        self.store.save_settings({'workdays_only':False,'work_hours_enabled':True,'work_start_minutes':1320,'work_end_minutes':360})
        until=finish_workday(self.store,stamp('2026-10-10T03:00'))
        self.assertEqual(until,stamp('2026-10-11T22:00'))
        self.assertFalse(automatic_state(self.store,stamp('2026-10-11T02:00'))['due'])
        self.assertTrue(automatic_state(self.store,until)['due'])

    def test_early_resume_keeps_disabled_automatic_preference(self):
        self.store.save_settings({'automatic':False})
        until=finish_workday(self.store,stamp('2026-10-09T17:00'))
        self.assertTrue(automatic_state(self.store,until-1)['off_duty'])
        self.store.put_meta('off_duty_until',0)
        self.assertFalse(automatic_state(self.store,until-1)['off_duty'])
        self.assertFalse(automatic_state(self.store,until)['due'])
        self.assertFalse(self.store.settings()['automatic'])

    def test_calendar_refresh_pauses_with_off_duty(self):
        now=stamp('2026-10-09T17:00')
        self.store.put_meta('calendar_2026',dict(self.calendar,updated_at=now-90000))
        self.assertTrue(refresh_needed(self.store,now))
        finish_workday(self.store,now)
        self.assertFalse(refresh_needed(self.store,now))


if __name__=='__main__': unittest.main()
