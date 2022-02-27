package main

import (
	"log"
	"sync"

	sieve "sieve.client"
)

type TestCoordinator struct {
	Server *testCoordinator
}

type testCoordinator struct {
	testPlan                     *TestPlan
	actionConext                 *ActionContext
	stateNotificationCh          chan TriggerNotification
	apiServerPauseNotificationCh chan *APIServerPauseNotification
	objectStates                 map[string]map[string]map[string]string
	objectStatesLock             sync.RWMutex
	mergedFieldPathMask          map[string]map[string]struct{}
	mergedFieldKeyMask           map[string]map[string]struct{}
	stateMachine                 *StateMachine
}

func NewTestCoordinator() *TestCoordinator {
	config := getConfig()
	testPlan := parseTestPlan(config)
	asyncDoneCh := make(chan *AsyncDoneNotification)
	actionConext := &ActionContext{
		namespace:          "default",
		leadingAPIServer:   "kind-control-plane",
		followingAPIServer: "kind-control-plane3",
		controllerLock:     &sync.Mutex{},
		controllerLocked:   false,
		apiserverLocks:     map[string]map[string]chan string{},
		apiserverLockedMap: map[string]map[string]bool{},
		asyncDoneCh:        asyncDoneCh,
	}
	mergedFieldPathMask, mergedFieldKeyMask := getMergedMask()
	stateNotificationCh := make(chan TriggerNotification, 500)
	apiServerPauseNotificationCh := make(chan *APIServerPauseNotification, 100)
	server := &testCoordinator{
		testPlan:                     testPlan,
		actionConext:                 actionConext,
		stateNotificationCh:          stateNotificationCh,
		apiServerPauseNotificationCh: apiServerPauseNotificationCh,
		objectStates:                 map[string]map[string]map[string]string{},
		mergedFieldPathMask:          mergedFieldPathMask,
		mergedFieldKeyMask:           mergedFieldKeyMask,
		stateMachine:                 NewStateMachine(testPlan, stateNotificationCh, apiServerPauseNotificationCh, asyncDoneCh, actionConext),
	}
	listener := &TestCoordinator{
		Server: server,
	}
	listener.Server.Start()
	return listener
}

func (l *TestCoordinator) NotifyTestBeforeAPIServerRecv(request *sieve.NotifyTestBeforeAPIServerRecvRequest, response *sieve.Response) error {
	return l.Server.NotifyTestBeforeAPIServerRecv(request, response)
}

func (l *TestCoordinator) NotifyTestAfterAPIServerRecv(request *sieve.NotifyTestAfterAPIServerRecvRequest, response *sieve.Response) error {
	return l.Server.NotifyTestAfterAPIServerRecv(request, response)
}

func (l *TestCoordinator) NotifyTestBeforeControllerRecv(request *sieve.NotifyTestBeforeControllerRecvRequest, response *sieve.Response) error {
	return l.Server.NotifyTestBeforeControllerRecv(request, response)
}

func (l *TestCoordinator) NotifyTestAfterControllerRecv(request *sieve.NotifyTestAfterControllerRecvRequest, response *sieve.Response) error {
	return l.Server.NotifyTestAfterControllerRecv(request, response)
}

func (l *TestCoordinator) NotifyTestAfterControllerGet(request *sieve.NotifyTestAfterControllerGetRequest, response *sieve.Response) error {
	return l.Server.NotifyTestAfterControllerGet(request, response)
}

func (l *TestCoordinator) NotifyTestAfterControllerList(request *sieve.NotifyTestAfterControllerListRequest, response *sieve.Response) error {
	return l.Server.NotifyTestAfterControllerList(request, response)
}

func (l *TestCoordinator) NotifyTestAfterControllerWrite(request *sieve.NotifyTestAfterControllerWriteRequest, response *sieve.Response) error {
	return l.Server.NotifyTestAfterControllerWrite(request, response)
}

func (s *testCoordinator) Start() {
	log.Println("start testCoordinator...")
	log.Printf("mergedFieldPathMask:\n%v\n", s.mergedFieldPathMask)
	log.Printf("mergedFieldKeyMask:\n%v\n", s.mergedFieldKeyMask)
	go s.stateMachine.run()
}

func (s *testCoordinator) SendObjectCreateNotificationAndBlock(handlerName, resourceKey, observedWhen, observedBy string) {
	blockingCh := make(chan string)
	notification := &ObjectCreateNotification{
		resourceKey:  resourceKey,
		observedWhen: observedWhen,
		observedBy:   observedBy,
		blockingCh:   blockingCh,
	}
	log.Printf("%s: send ObjectCreateNotification\n", handlerName)
	s.stateNotificationCh <- notification
	<-blockingCh
	log.Printf("%s: block over for ObjectCreateNotification\n", handlerName)
}

func (s *testCoordinator) SendObjectDeleteNotificationAndBlock(handlerName, resourceKey, observedWhen, observedBy string) {
	blockingCh := make(chan string)
	notification := &ObjectDeleteNotification{
		resourceKey:  resourceKey,
		observedWhen: observedWhen,
		observedBy:   observedBy,
		blockingCh:   blockingCh,
	}
	log.Printf("%s: send ObjectDeleteNotification\n", handlerName)
	s.stateNotificationCh <- notification
	<-blockingCh
	log.Printf("%s: block over for ObjectDeleteNotification\n", handlerName)
}

func (s *testCoordinator) SendObjectUpdateNotificationAndBlock(handlerName, resourceKey, observedWhen, observedBy string, prevState, curState map[string]interface{}) {
	blockingCh := make(chan string)
	notification := &ObjectUpdateNotification{
		resourceKey:   resourceKey,
		observedWhen:  observedWhen,
		observedBy:    observedBy,
		prevState:     prevState,
		curState:      curState,
		fieldKeyMask:  s.mergedFieldKeyMask[resourceKey],
		fieldPathMask: s.mergedFieldPathMask[resourceKey],
		blockingCh:    blockingCh,
	}
	log.Printf("%s: send ObjectUpdateNotification\n", handlerName)
	s.stateNotificationCh <- notification
	<-blockingCh
	log.Printf("%s: block over for ObjectUpdateNotification\n", handlerName)
}

func (s *testCoordinator) InitializeObjectStatesEntry(observedBy, observedWhen, resourceKey string) {
	s.objectStatesLock.Lock()
	defer s.objectStatesLock.Unlock()
	if _, ok := s.objectStates[observedBy]; !ok {
		s.objectStates[observedBy] = map[string]map[string]string{}
	}
	if _, ok := s.objectStates[observedBy][observedWhen]; !ok {
		s.objectStates[observedBy][observedWhen] = map[string]string{}
	}
	if _, ok := s.objectStates[observedBy][observedWhen][resourceKey]; !ok {
		s.objectStates[observedBy][observedWhen][resourceKey] = "{}"
	}
}

func (s *testCoordinator) ReadFromObjectStates(observedBy, observedWhen, resourceKey string) string {
	s.objectStatesLock.RLock()
	defer s.objectStatesLock.RUnlock()
	return s.objectStates[observedBy][observedWhen][resourceKey]
}

func (s *testCoordinator) WriteToObjectStates(observedBy, observedWhen, resourceKey string, value string) {
	s.objectStatesLock.Lock()
	defer s.objectStatesLock.Unlock()
	s.objectStates[observedBy][observedWhen][resourceKey] = value
}

func (s *testCoordinator) SendAPIServerPauseNotificationAndBlock(handlerName, apiserverName, resourceKey string, pausedByAll bool) {
	pausingCh := make(chan string)
	notification := &APIServerPauseNotification{
		apiServerName: apiserverName,
		resourceKey:   resourceKey,
		pausedByAll:   pausedByAll,
		blockingCh:    pausingCh,
	}
	log.Printf("%s: send APIServerPauseNotification\n", handlerName)
	s.apiServerPauseNotificationCh <- notification
	<-pausingCh
	log.Printf("%s: block over for APIServerPauseNotification\n", handlerName)
}

func (s *testCoordinator) APIServerPauseOrReturn(handlerName, apiServerHostname, pauseScope string) {
	if _, ok := s.actionConext.apiserverLockedMap[apiServerHostname]; ok {
		if val, ok := s.actionConext.apiserverLockedMap[apiServerHostname][pauseScope]; ok {
			if val {
				s.SendAPIServerPauseNotificationAndBlock(handlerName, apiServerHostname, pauseScope, false)
				return
			}
		}
		if val, ok := s.actionConext.apiserverLockedMap[apiServerHostname]["all"]; ok {
			if val {
				s.SendAPIServerPauseNotificationAndBlock(handlerName, apiServerHostname, pauseScope, true)
				return
			}
		}
	}
}

func (s *testCoordinator) NotifyTestBeforeAPIServerRecv(request *sieve.NotifyTestBeforeAPIServerRecvRequest, response *sieve.Response) error {
	handlerName := "NotifyTestBeforeAPIServerRecv"
	log.Printf("%s\t%s\t%s\t%s\t%s", request.APIServerHostname, handlerName, request.OperationType, request.ResourceKey, request.Object)
	s.InitializeObjectStatesEntry(request.APIServerHostname, beforeAPIServerRecv, request.ResourceKey)
	switch request.OperationType {
	case API_ADDED:
		s.SendObjectCreateNotificationAndBlock(handlerName, request.ResourceKey, beforeAPIServerRecv, request.APIServerHostname)
	case API_MODIFIED:
		prevObjectStateStr := s.ReadFromObjectStates(request.APIServerHostname, beforeAPIServerRecv, request.ResourceKey)
		s.SendObjectUpdateNotificationAndBlock(handlerName, request.ResourceKey, beforeAPIServerRecv, request.APIServerHostname, strToMap(prevObjectStateStr), strToMap(request.Object))
	case API_DELETED:
		s.SendObjectDeleteNotificationAndBlock(handlerName, request.ResourceKey, beforeAPIServerRecv, request.APIServerHostname)
	default:
		log.Printf("do not support %s\n", request.OperationType)
	}
	s.WriteToObjectStates(request.APIServerHostname, beforeAPIServerRecv, request.ResourceKey, request.Object)
	s.APIServerPauseOrReturn(handlerName, request.APIServerHostname, request.ResourceKey)
	*response = sieve.Response{Message: "", Ok: true}
	return nil
}

func (s *testCoordinator) NotifyTestAfterAPIServerRecv(request *sieve.NotifyTestAfterAPIServerRecvRequest, response *sieve.Response) error {
	handlerName := "NotifyTestAfterAPIServerRecv"
	log.Printf("%s\t%s\t%s\t%s\t%s", request.APIServerHostname, handlerName, request.OperationType, request.ResourceKey, request.Object)
	s.InitializeObjectStatesEntry(request.APIServerHostname, afterAPIServerRecv, request.ResourceKey)
	switch request.OperationType {
	case API_ADDED:
		s.SendObjectCreateNotificationAndBlock(handlerName, request.ResourceKey, afterAPIServerRecv, request.APIServerHostname)
	case API_MODIFIED:
		prevObjectStateStr := s.ReadFromObjectStates(request.APIServerHostname, afterAPIServerRecv, request.ResourceKey)
		s.SendObjectUpdateNotificationAndBlock(handlerName, request.ResourceKey, afterAPIServerRecv, request.APIServerHostname, strToMap(prevObjectStateStr), strToMap(request.Object))
	case API_DELETED:
		s.SendObjectDeleteNotificationAndBlock(handlerName, request.ResourceKey, afterAPIServerRecv, request.APIServerHostname)
	default:
		log.Printf("do not support %s\n", request.OperationType)
	}
	s.WriteToObjectStates(request.APIServerHostname, afterAPIServerRecv, request.ResourceKey, request.Object)
	s.APIServerPauseOrReturn(handlerName, request.APIServerHostname, request.ResourceKey)
	*response = sieve.Response{Message: "", Ok: true}
	return nil
}

func (s *testCoordinator) NotifyTestBeforeControllerRecv(request *sieve.NotifyTestBeforeControllerRecvRequest, response *sieve.Response) error {
	handlerName := "NotifyTestBeforeControllerRecv"
	log.Printf("%s\t%s\t%s\t%s", handlerName, request.OperationType, request.ResourceKey, request.Object)
	switch request.OperationType {
	case HEAR_ADDED:
		s.SendObjectCreateNotificationAndBlock(handlerName, request.ResourceKey, beforeControllerRecv, "")
	case HEAR_DELETED:
		s.SendObjectDeleteNotificationAndBlock(handlerName, request.ResourceKey, beforeControllerRecv, "")
	default:
		log.Printf("do not support %s\n", request.OperationType)
	}
	*response = sieve.Response{Message: "", Ok: true}
	return nil
}

func (s *testCoordinator) NotifyTestAfterControllerRecv(request *sieve.NotifyTestAfterControllerRecvRequest, response *sieve.Response) error {
	handlerName := "NotifyTestAfterControllerRecv"
	log.Printf("%s\t%s\t%s\t%s", handlerName, request.OperationType, request.ResourceKey, request.Object)
	switch request.OperationType {
	case HEAR_ADDED:
		s.SendObjectCreateNotificationAndBlock(handlerName, request.ResourceKey, afterControllerRecv, "")
	case HEAR_DELETED:
		s.SendObjectDeleteNotificationAndBlock(handlerName, request.ResourceKey, afterControllerRecv, "")
	default:
		log.Printf("do not support %s\n", request.OperationType)
	}
	*response = sieve.Response{Message: "", Ok: true}
	return nil
}

func (s *testCoordinator) NotifyTestAfterControllerGet(request *sieve.NotifyTestAfterControllerGetRequest, response *sieve.Response) error {
	log.Printf("NotifyTestAfterControllerGet\t%s\t%s\t%s", request.ResourceKey, request.ReconcilerType, request.Object)
	s.InitializeObjectStatesEntry(request.ReconcilerType, afterControllerWrite, request.ResourceKey)
	s.WriteToObjectStates(request.ReconcilerType, afterControllerWrite, request.ResourceKey, request.Object)
	*response = sieve.Response{Message: "", Ok: true}
	return nil
}

func (s *testCoordinator) NotifyTestAfterControllerList(request *sieve.NotifyTestAfterControllerListRequest, response *sieve.Response) error {
	log.Printf("NotifyTestAfterControllerList\t%s\t%s\t%s", request.ResourceType, request.ReconcilerType, request.ObjectList)
	objects := strToMap(request.ObjectList)["items"].([]interface{})
	for _, object := range objects {
		objectState := object.(map[string]interface{})
		name, namespace := extractNameNamespaceFromObjMap(objectState)
		resourceKey := generateResourceKey(request.ResourceType, namespace, name)
		s.InitializeObjectStatesEntry(request.ReconcilerType, afterControllerWrite, resourceKey)
		s.WriteToObjectStates(request.ReconcilerType, afterControllerWrite, resourceKey, mapToStr(objectState))
	}
	*response = sieve.Response{Message: "", Ok: true}
	return nil
}

func (s *testCoordinator) NotifyTestAfterControllerWrite(request *sieve.NotifyTestAfterControllerWriteRequest, response *sieve.Response) error {
	handlerName := "NotifyTestAfterControllerWrite"
	log.Printf("%s\t%s\t%s\t%s\t%s", handlerName, request.WriteType, request.ResourceKey, request.ReconcilerType, request.Object)
	s.InitializeObjectStatesEntry(request.ReconcilerType, afterControllerWrite, request.ResourceKey)
	prevObjectStateStr := s.ReadFromObjectStates(request.ReconcilerType, afterControllerWrite, request.ResourceKey)
	switch request.WriteType {
	case WRITE_CREATE:
		s.SendObjectCreateNotificationAndBlock(handlerName, request.ResourceKey, afterControllerWrite, request.ReconcilerType)
	case WRITE_UPDATE, WRITE_PATCH, WRITE_STATUS_UPDATE, WRITE_STATUS_PATCH:
		prevObjectState := strToMap(prevObjectStateStr)
		trimKindApiversion(prevObjectState)
		curObjectState := strToMap(request.Object)
		trimKindApiversion(curObjectState)
		s.SendObjectUpdateNotificationAndBlock(handlerName, request.ResourceKey, afterControllerWrite, request.ReconcilerType, prevObjectState, curObjectState)
	case WRITE_DELETE:
		s.SendObjectDeleteNotificationAndBlock(handlerName, request.ResourceKey, afterControllerWrite, request.ReconcilerType)
	default:
		log.Printf("do not support %s\n", request.WriteType)
	}
	*response = sieve.Response{Message: "", Ok: true}
	return nil
}