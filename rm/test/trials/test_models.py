"""
Unittests for Randomise.me models
"""
import datetime
import unittest

from django.core import mail
from django.test import utils, TestCase
from mock import MagicMock, patch

from rm import exceptions
from rm.trials import models

def setup_module():
    utils.setup_test_environment()

def teardown_module():
    utils.teardown_test_environment()

class TemporalTestCase(TestCase):
    def setUp(self):
        super(TemporalTestCase, self).setUp()
        self.today = datetime.date.today()
        self.yesterday = self.today - datetime.timedelta(days=1)
        self.tomorrow = self.today + datetime.timedelta(days=1)


class TrialTestCase(TemporalTestCase):

    def test_can_join_finished(self):
        "Can't join a finished trial"
        trial = models.Trial(stopped=True)
        self.assertEqual(False, trial.can_join())

    def test_can_join_n1trial(self):
        "Can't join a n=1 trial"
        trial = models.Trial(n1trial=True)
        self.assertEqual(False, trial.can_join())

    @patch.object(models.Trial, 'participant_set')
    def test_can_join_with_participants(self, pset):
        "Can join an open trial"
        trial = models.Trial()
        pset.count.return_value = 1
        self.assertEqual(True, trial.can_join())

    def test_ensure_groups(self):
        "Get or greate for a & b groups"
        trial = models.Trial()
        with patch.object(models.Group.objects, 'get_or_create') as pgc:
            trial.ensure_groups()
            self.assertEqual(2, pgc.call_count)
            pgc.assert_any_call(trial=trial, name='A')
            pgc.assert_any_call(trial=trial, name='B')

    def test_join_is_owner(self):
        "Should raise"
        user = models.User(pk=2, email='larry@example.com')
        trial = models.Trial(owner=user, min_participants=20)
        trial.save()
        variable = models.Variable(question="Why", trial=trial)
        variable.save()
        trial.join(user)
        self.assertEqual(1, trial.participant_set.filter(user=user).count())

    def test_join_finished_trial(self):
        "Should raise"
        owner = models.User(pk=1)
        user = models.User(pk=2)
        trial = models.Trial(owner=owner, stopped=True)
        with self.assertRaises(exceptions.TrialFinishedError):
            trial.join(user)

    def test_join_second_time(self):
        "should raise"
        owner = models.User(pk=1)
        with patch.object(models.Participant.objects, 'filter') as pfilt:
            pfilt.return_value.count.return_value = 1
            trial = models.Trial(owner=owner)
            user = models.User()
            with self.assertRaises(exceptions.AlreadyJoinedError):
                trial.join(user)
            pfilt.assert_called_once_with(trial=trial, user=user)

    def test_join(self):
        "Should create participant"
        owner = models.User(pk=1)
        trial = models.Trial(owner=owner, min_participants=2)
        trial.save()
        user = models.User(pk=2)
        with patch.object(models, 'Participant') as ppart:
            ppart.objects.filter.return_value.count.return_value = 0
            trial.join(user)
            ppart.objects.filter.assert_called_once_with(trial=trial, user=user)
            ppart.objects.filter.return_value.count.assert_called_once_with()
            ppart.assert_called_once_with(trial=trial, user=user)

    @patch.object(models.Trial, 'participant_set')
    def test_randomise_second_time(self, pset):
        "Should raise"
        pset.filter.return_value.count.return_value = 2
        trial = models.Trial()
        with self.assertRaises(exceptions.AlreadyRandomisedError):
            trial.randomise()
        pset.filter.assert_called_once_with(group__isnull=False)
        pset.filter.return_value.count.assert_called_once_with()

    @patch.object(models.Trial, 'participant_set')
    def test_randomise(self, pset):
        "Randomise the participants"
        trial = models.Trial()
        part1, part2 = MagicMock(), MagicMock()
        pset.all.return_value = [part1, part2]
        pset.filter.return_value.count.return_value = 0

        groups = [models.Group(trial=trial, name='A'),
                  models.Group(trial=trial, name='B')]

        with patch.object(trial, 'ensure_groups') as psure:
            psure.return_value = groups

            trial.randomise()
            for participant in [part1, part2]:
                self.assertTrue(participant.group in groups)
                participant.save.assert_called_once_with()

    def test_send_instructions_finished(self):
        "Should raise"
        trial = models.Trial(stopped=True)
        with self.assertRaises(exceptions.TrialFinishedError):
            trial.send_instructions()

    @patch.object(models.Trial, 'participant_set')
    def test_send_instructions(self, pset):
        "Should email participants."
        part1, part2 = MagicMock(), MagicMock()
        pset.all.return_value = [part1, part2]
        trial = models.Trial()
        trial.send_instructions()
        for participant in [part1, part2]:
            participant.send_instructions.assert_called_once_with()

    def test_is_invitation_only(self):
        "Model predicates"
        trial = models.Trial()
        self.assertEqual(False, trial.is_invitation_only)
        trial.recruitment = trial.INVITATION
        self.assertEqual(True, trial.is_invitation_only)




class ParticipantTestCase(TestCase):

    def setUp(self):
        super(ParticipantTestCase, self).setUp()
        self.user = models.User(email='larry@example.com', pk=1)
        self.trial = models.Trial(pk=1, title='This', group_a='Do it', min_participants=20, owner=self.user)
        self.trial.save()
        self.variable = models.Variable(question='Why?', trial=self.trial)
        self.variable.save()
        self.group = models.Group(trial=self.trial, name='A')
        self.participant = models.Participant(user=self.user,
                                              trial=self.trial,
                                              group=self.group)

    def test_send_instructions_no_to_email(self):
        "Should raise"
        self.user.email = ''
        with self.assertRaises(exceptions.NoEmailError):
            self.participant.send_instructions()

    def test_send_instructions_subject(self):
        "Should send email"
        self.participant.send_instructions()
        self.assertEqual(1, len(mail.outbox))
        self.assertEqual(
            'Randomise.me - instructions for This',
            mail.outbox[0].subject)

    def test_send_instructions_body(self):
        "Should include instructions"
        self.participant.send_instructions()
        self.assertEqual(1, len(mail.outbox))
        for content in [mail.outbox[0].body, mail.outbox[0].alternatives[0][0]]:
            self.assertNotEqual(-1, content.find('Do it'))

    def test_send_instructions_from(self):
        "Should be from email"
        with self.settings(DEFAULT_FROM_EMAIL='from@example.com'):
            self.participant.send_instructions()
        self.assertEqual(1, len(mail.outbox))
        self.assertEqual('from@example.com', mail.outbox[0].from_email)

    def test_send_instructions_to(self):
        "Should be the owner's email"
        self.user.email = 'larry@example.com'
        self.participant.send_instructions()
        self.assertEqual(1, len(mail.outbox))
        self.assertEqual(['larry@example.com'], mail.outbox[0].to)


class ReportTestCase(TestCase):

    def test_reported_score(self):
        "predicateability"
        trial = models.Trial(pk=1)
        variable = models.Variable(style=models.Variable.SCORE)
        report = models.Report(trial=trial, variable=variable)
        self.assertEqual(False, report.reported())
        report.score = 3
        self.assertEqual(True, report.reported())

    def test_reported_binary(self):
        "predicateability"
        trial = models.Trial(pk=1)
        variable = models.Variable(style=models.Variable.BINARY)
        report = models.Report(trial=trial, variable=variable)
        self.assertEqual(False, report.reported())
        report.binary = True
        self.assertEqual(True, report.reported())

    def test_reported_count(self):
        "predicateability"
        trial = models.Trial(pk=1)
        variable = models.Variable(style=models.Variable.COUNT)
        report = models.Report(trial=trial, variable=variable)
        self.assertEqual(False, report.reported())
        report.count = 2
        self.assertEqual(True, report.reported())


    def test_get_value_score(self):
        "predicateability"
        trial = models.Trial(pk=1)
        variable = models.Variable(style=models.Variable.SCORE)
        report = models.Report(trial=trial, variable=variable)
        self.assertEqual(None, report.get_value())
        report.score = 3
        self.assertEqual(3, report.get_value())

    def test_get_value_binary(self):
        "predicateability"
        trial = models.Trial(pk=1)
        variable = models.Variable(style=models.Variable.BINARY)
        report = models.Report(trial=trial, variable=variable)
        self.assertEqual(None, report.get_value())
        report.binary = True
        self.assertEqual(True, report.get_value())

    def test_get_value_count(self):
        "predicateability"
        trial = models.Trial(pk=1)
        variable = models.Variable(style=models.Variable.COUNT)
        report = models.Report(trial=trial, variable=variable)
        self.assertEqual(None, report.get_value())
        report.count = 2
        self.assertEqual(2, report.get_value())



if __name__ == '__main__':
    unittest.main()
