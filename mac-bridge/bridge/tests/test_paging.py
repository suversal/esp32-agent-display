import unittest

from bridge.paging import Pager


def snapshot(count=8, rich=True, alert=None):
    return dict(type="snapshot",v=2,server_time=1800000000,current_sound_seq=17,alert=alert,
                sessions=[dict(key=f"session-{i}",state="running",title=f"任务{i}" if rich else "",project=f"repo-{i}") for i in range(count)])


class PagingTests(unittest.TestCase):
    def test_every_session_is_reachable_with_bounded_device_memory(self):
        source=snapshot(128)
        pager=Pager(0)
        seen=[]
        for i in range(43):
            page=pager.view(source,1)
            self.assertEqual(page['page']['index'],i)
            self.assertEqual(page['page']['count'],43)
            self.assertLessEqual(len(page['sessions']),3)
            self.assertEqual(page['total_sessions'],128)
            self.assertEqual(page['current_sound_seq'],17)
            seen.extend(row['key'] for row in page['sessions'])
            pager.request('next',1)
        self.assertEqual(len(set(seen)),128)
        self.assertEqual(len(source['sessions']),128)
        self.assertEqual(pager.view(source,1)['page']['index'],0)

    def test_rotation_respects_manual_reading_hold_despite_frequent_updates(self):
        source=snapshot()
        pager=Pager(0)
        self.assertEqual(pager.view(source,0)['page']['index'],0)
        self.assertEqual(pager.view(source,19.99)['page']['index'],0)
        self.assertEqual(pager.view(source,20)['page']['index'],1)
        pager.request('next',21)
        self.assertEqual(pager.view(source,21)['page']['hold_seconds'],60)
        for now in range(22,81):
            self.assertEqual(pager.view(source,now)['page']['index'],2)
        self.assertEqual(pager.view(source,81)['page']['index'],0)
        self.assertEqual(pager.auto_rotations,2)

    def test_pause_persists_until_explicit_resume_and_next_still_works(self):
        source=snapshot()
        pager=Pager(0)
        pager.view(source,0)
        pager.request('toggle_auto',1)
        self.assertFalse(pager.view(source,1000)['page']['auto'])
        self.assertEqual(pager.index,0)
        pager.request('next',1001)
        self.assertEqual(pager.view(source,2000)['page']['index'],1)
        pager.request('toggle_auto',2001)
        self.assertEqual(pager.view(source,2020)['page']['index'],1)
        self.assertEqual(pager.view(source,2021)['page']['index'],2)

    def test_new_urgent_alert_focuses_its_page_and_waits_for_ack(self):
        source=snapshot()
        pager=Pager(0)
        pager.view(source,0)
        source['alert']=dict(kind='waiting',alert_id='urgent',session_key='session-7',sound='none')
        page=pager.view(source,1)
        self.assertEqual(page['page']['index'],2)
        self.assertTrue(page['page']['waiting'])
        self.assertIn('session-7',[r['key'] for r in page['sessions']])
        self.assertFalse(pager.request('next',2))
        self.assertEqual(pager.view(source,100)['page']['index'],2)
        source['alert']=None  # Ack does not resolve the underlying waiting session.
        source['sessions'][7]['state']='waiting'
        self.assertEqual(pager.view(source,101)['page']['index'],2)
        self.assertEqual(pager.view(source,120)['page']['index'],2)
        self.assertEqual(pager.view(source,121)['page']['index'],0)
        self.assertEqual(source['sessions'][7]['state'],'waiting')

    def test_activity_reordering_does_not_shuffle_the_reading_page(self):
        source=snapshot()
        pager=Pager(0)
        first=pager.view(source,0)
        source['sessions'].reverse()
        second=pager.view(source,1)
        self.assertEqual([r['key'] for r in first['sessions']],[r['key'] for r in second['sessions']])
        source['sessions'].append(dict(key='new-session',state='running',title='新任务'))
        self.assertEqual(pager.view(source,2)['sessions'],second['sessions'])

    def test_running_sessions_move_before_completed_cards_when_state_changes(self):
        source=snapshot(8)
        for row in source['sessions']:
            row['state']='done'
        pager=Pager(0)
        pager.view(source,0)
        source['sessions'][7]['state']='running'
        page=pager.view(source,1)
        self.assertEqual(page['page']['index'],0)
        self.assertEqual(page['sessions'][0]['key'],'session-7')
        # New running sessions join the running group ahead of older done cards.
        source['sessions'].append(dict(key='new-running',state='running',title='新任务'))
        page=pager.view(source,2)
        self.assertEqual([r['key'] for r in page['sessions']],['session-7','new-running','session-0'])
        source['sessions'].reverse()
        self.assertEqual(pager.view(source,3)['sessions'],page['sessions'])
        source['sessions'][0]['state']='done'  # new-running has finished.
        page=pager.view(source,4)
        self.assertEqual([r['state'] for r in page['sessions']],['running','done','done'])
        self.assertEqual(page['current_sound_seq'],17)
        self.assertIsNone(page['alert'])

    def test_priority_changes_preserve_manual_page_pause_and_hold(self):
        source=snapshot(8)
        for row in source['sessions']:
            row['state']='done'
        pager=Pager(0)
        pager.view(source,0)
        pager.request('toggle_auto',1)
        pager.request('next',2)
        source['sessions'][7]['state']='running'
        page=pager.view(source,3)
        self.assertEqual(pager.order[0],'session-7')
        self.assertEqual(page['page']['index'],1)
        self.assertFalse(page['page']['auto'])
        self.assertEqual(page['page']['hold_seconds'],59)
        self.assertEqual(pager.view(source,100)['page']['index'],1)

    def test_pending_alert_stays_visible_after_state_priority_changes(self):
        source=snapshot(8,alert=dict(kind='waiting',alert_id='urgent',session_key='session-7'))
        for row in source['sessions']:
            row['state']='done'
        pager=Pager(0)
        self.assertEqual(pager.view(source,0)['page']['index'],2)
        source['sessions'][7]['state']='waiting'
        source['sessions'][6]['state']='running'
        page=pager.view(source,1)
        self.assertEqual(page['page']['index'],0)
        self.assertEqual([r['key'] for r in page['sessions']][:2],['session-7','session-6'])
        self.assertTrue(page['page']['waiting'])
        self.assertFalse(pager.request('next',2))
        self.assertEqual(page['alert'],source['alert'])

    def test_removals_empty_pages_legacy_cards_and_clients_are_independent(self):
        source=snapshot(9)
        first,second=Pager(0),Pager(0,auto=False)
        first.view(source,0); second.view(source,0)
        first.request('next',1); first.request('next',2)
        self.assertEqual(second.view(source,3)['page']['index'],0)
        source['sessions']=source['sessions'][:2]
        page=first.view(source,4)
        self.assertEqual(page['page']['index'],0)
        self.assertEqual(len(page['sessions']),2)
        self.assertEqual(first.view(snapshot(0),5)['page']['count'],1)
        self.assertFalse(first.due(1000))
        legacy=first.view(snapshot(9,rich=False),1001)
        self.assertEqual(legacy['page']['size'],4)
        self.assertEqual(legacy['page']['count'],3)
        self.assertEqual(len(legacy['sessions']),4)
        self.assertFalse(first.request('unexpected',1002))


if __name__=='__main__':unittest.main()
