package main

type TriggerNotification interface {
	getBlockingCh() chan string
}

type TimeoutNotification struct {
	conditionName string
}

func (n *TimeoutNotification) getBlockingCh() chan string {
	return nil
}

type AnnotatedAPICallNotification struct {
	module       string
	filePath     string
	receiverType string
	funName      string
	observedWhen string
	observedBy   string
	blockingCh   chan string
}

func (n *AnnotatedAPICallNotification) getBlockingCh() chan string {
	return n.blockingCh
}

type ObjectCreateNotification struct {
	resourceKey  string
	observedWhen string
	observedBy   string
	blockingCh   chan string
}

func (n *ObjectCreateNotification) getBlockingCh() chan string {
	return n.blockingCh
}

type ObjectDeleteNotification struct {
	resourceKey  string
	observedWhen string
	observedBy   string
	blockingCh   chan string
}

func (n *ObjectDeleteNotification) getBlockingCh() chan string {
	return n.blockingCh
}

type ObjectUpdateNotification struct {
	resourceKey          string
	observedWhen         string
	observedBy           string
	prevState            map[string]interface{}
	curState             map[string]interface{}
	fieldKeyMask         map[string]struct{}
	fieldPathMask        map[string]struct{}
	fieldKeyMaskAPIForm  map[string]struct{}
	fieldPathMaskAPIForm map[string]struct{}
	blockingCh           chan string
}

func (n *ObjectUpdateNotification) getBlockingCh() chan string {
	return n.blockingCh
}

type AsyncDoneNotification struct {
}
