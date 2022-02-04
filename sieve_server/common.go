package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io/ioutil"
	"log"
	"strconv"
	"time"

	"gopkg.in/yaml.v2"
	appsv1 "k8s.io/api/apps/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/labels"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/tools/clientcmd"
)

func checkError(err error) {
	if err != nil {
		log.Fatalf("Fail due to error: %v\n", err)
	}
}

func getConfig() map[interface{}]interface{} {

	data, err := ioutil.ReadFile("server.yaml")
	checkError(err)
	m := make(map[interface{}]interface{})

	err = yaml.Unmarshal([]byte(data), &m)
	checkError(err)
	log.Printf("config:\n%v\n", m)

	return m
}

func getMask() (map[string][]string, map[string][]string) {
	data, err := ioutil.ReadFile("learned-mask.json")
	checkError(err)
	learnedMask := make(map[string][]string)

	err = yaml.Unmarshal([]byte(data), &learnedMask)
	checkError(err)
	log.Printf("learned mask:\n%v\n", learnedMask)

	data, err = ioutil.ReadFile("configured-mask.json")
	checkError(err)
	configuredMask := make(map[string][]string)

	err = yaml.Unmarshal([]byte(data), &configuredMask)
	checkError(err)
	log.Printf("configured mask:\n%v\n", configuredMask)

	return learnedMask, configuredMask
}

func mergeAndRefineMask(resourceType, resourceNamespace, resourceName string, learnedMask map[string][]string, configuredMask map[string][]string) (map[string]struct{}, map[string]struct{}) {
	maskedKeysSet := make(map[string]struct{})
	maskedPathsSet := make(map[string]struct{})

	resourceKey := fmt.Sprintf("%s/%s/%s", resourceType, resourceNamespace, resourceName)

	learnedMaskedPathsList := learnedMask[resourceKey]
	for _, val := range learnedMaskedPathsList {
		maskedPathsSet[val] = exists
	}

	for _, val := range configuredMask["paths"] {
		maskedPathsSet[val] = exists
	}

	for _, val := range configuredMask["keys"] {
		maskedKeysSet[val] = exists
	}

	return maskedKeysSet, maskedPathsSet
}

func strToMap(str string) map[string]interface{} {
	m := make(map[string]interface{})
	err := json.Unmarshal([]byte(str), &m)
	if err != nil {
		log.Fatalf("cannot unmarshal to map: %s\n", str)
	}
	return m
}

func strToInt(str string) int {
	i, err := strconv.Atoi(str)
	if err != nil {
		log.Fatalf("cannot conver to int: %s\n", str)
	}
	return i
}

func strToBool(str string) bool {
	b, err := strconv.ParseBool(str)
	if err != nil {
		log.Fatalf("cannot conver to bool: %s\n", str)
	}
	return b
}

func deepCopyMap(src map[string]interface{}) map[string]interface{} {
	dest := make(map[string]interface{})
	if src == nil {
		log.Fatalf("src is nil. You cannot read from a nil map")
	}
	jsonStr, err := json.Marshal(src)
	if err != nil {
		log.Fatalf(err.Error())
	}
	err = json.Unmarshal(jsonStr, &dest)
	if err != nil {
		log.Fatalf(err.Error())
	}
	return dest
}

func startStaleStateInjection() {
	log.Println("START-SIEVE-STALE-STATE")
}

func startUnobsrStateInjection() {
	log.Println("START-SIEVE-UNOBSERVED-STATE")
}

func startIntmdStateInjection() {
	log.Println("START-SIEVE-INTERMEDIATE-STATE")
}

func finishStaleStateInjection() {
	log.Println("FINISH-SIEVE-STALE-STATE")
}

func finishUnobsrStateInjection() {
	log.Println("FINISH-SIEVE-UNOBSERVED-STATE")
}

func finishIntmdStateInjection() {
	log.Println("FINISH-SIEVE-INTERMEDIATE-STATE")
}

func extractNameNamespaceFromObjMap(objMap map[string]interface{}) (string, string) {
	name := ""
	namespace := ""
	if _, ok := objMap["metadata"]; ok {
		if metadataMap, ok := objMap["metadata"].(map[string]interface{}); ok {
			if _, ok := metadataMap["name"]; ok {
				name = metadataMap["name"].(string)
			}
			if _, ok := metadataMap["namespace"]; ok {
				namespace = metadataMap["namespace"].(string)
			}
		}
	} else {
		if _, ok := objMap["name"]; ok {
			name = objMap["name"].(string)
		}
		if _, ok := objMap["namespace"]; ok {
			namespace = objMap["namespace"].(string)
		}
	}
	return name, namespace
}

func isSameObjectServerSide(currentEvent map[string]interface{}, namespace string, name string) bool {
	extractedName, extractedNamespace := extractNameNamespaceFromObjMap(currentEvent)
	return extractedNamespace == namespace && extractedName == name
}

func waitForPodTermination(namespace, podLabel, leadingAPI string) {
	masterUrl := "https://" + leadingAPI + ":6443"
	config, err := clientcmd.BuildConfigFromFlags(masterUrl, "/root/.kube/config")
	checkError(err)
	clientset, err := kubernetes.NewForConfig(config)
	checkError(err)
	labelSelector := metav1.LabelSelector{MatchLabels: map[string]string{"sievetag": podLabel}}
	listOptions := metav1.ListOptions{
		LabelSelector: labels.Set(labelSelector.MatchLabels).String(),
	}
	for {
		time.Sleep(time.Duration(1) * time.Second)
		pods, err := clientset.CoreV1().Pods(namespace).List(context.TODO(), listOptions)
		checkError(err)
		if len(pods.Items) != 0 {
			log.Printf("operator pod not deleted yet\n")
		} else {
			log.Printf("operator pod gets deleted\n")
			break
		}
	}
}

func waitForPodRunning(namespace, podLabel, leadingAPI string) {
	masterUrl := "https://" + leadingAPI + ":6443"
	config, err := clientcmd.BuildConfigFromFlags(masterUrl, "/root/.kube/config")
	checkError(err)
	clientset, err := kubernetes.NewForConfig(config)
	checkError(err)
	labelSelector := metav1.LabelSelector{MatchLabels: map[string]string{"sievetag": podLabel}}
	listOptions := metav1.ListOptions{
		LabelSelector: labels.Set(labelSelector.MatchLabels).String(),
	}
	for {
		time.Sleep(time.Duration(1) * time.Second)
		pods, err := clientset.CoreV1().Pods(namespace).List(context.TODO(), listOptions)
		checkError(err)
		if len(pods.Items) == 0 {
			log.Printf("operator pod not created yet\n")
		} else {
			ready := true
			for i := 0; i < len(pods.Items); i++ {
				if pods.Items[i].Status.Phase == "Running" {
					log.Printf("operator pod %d ready now\n", i)
				} else {
					log.Printf("operator pod %d not ready yet\n", i)
					ready = false
				}
			}
			if ready {
				break
			}
		}
	}
}

func restartOperator(namespace, deployName, podLabel, leadingAPI, followingAPI string, redirect bool) {
	masterUrl := "https://" + leadingAPI + ":6443"
	config, err := clientcmd.BuildConfigFromFlags(masterUrl, "/root/.kube/config")
	checkError(err)
	clientset, err := kubernetes.NewForConfig(config)
	checkError(err)

	labelSelector := metav1.LabelSelector{MatchLabels: map[string]string{"sievetag": podLabel}}
	listOptions := metav1.ListOptions{
		LabelSelector: labels.Set(labelSelector.MatchLabels).String(),
	}

	pods, err := clientset.CoreV1().Pods(namespace).List(context.TODO(), listOptions)
	checkError(err)

	operatorPod := pods.Items[0]
	operatorOwnerName := ""
	operatorOwnerKind := ""
	log.Printf("operator pod owner type: %s", operatorPod.OwnerReferences[0].Kind)
	log.Printf("operator pod owner name: %s", operatorPod.OwnerReferences[0].Name)
	if operatorPod.OwnerReferences[0].Kind == "ReplicaSet" {
		ownerName := operatorPod.OwnerReferences[0].Name
		replicaset, err := clientset.AppsV1().ReplicaSets(namespace).Get(context.TODO(), ownerName, metav1.GetOptions{})
		checkError(err)
		log.Printf("replicaset owner type: %s", replicaset.OwnerReferences[0].Kind)
		log.Printf("replicaset owner name: %s", replicaset.OwnerReferences[0].Name)
		if replicaset.OwnerReferences[0].Kind == "Deployment" {
			operatorOwnerKind = replicaset.OwnerReferences[0].Kind
			operatorOwnerName = replicaset.OwnerReferences[0].Name
		} else {
			checkError(fmt.Errorf("the owner of the replicaset should be a deployment"))
		}
	} else if operatorPod.OwnerReferences[0].Kind == "StatefulSet" {
		operatorOwnerKind = operatorPod.OwnerReferences[0].Kind
		operatorOwnerName = operatorPod.OwnerReferences[0].Name
	} else {
		checkError(fmt.Errorf("the owner of the pod should be either replicaset or statefulset"))
	}

	if operatorOwnerKind == "Deployment" {
		deployment, err := clientset.AppsV1().Deployments(namespace).Get(context.TODO(), operatorOwnerName, metav1.GetOptions{})
		checkError(err)
		log.Println(deployment.Spec.Template.Spec.Containers[0].Env)
		clientset.AppsV1().Deployments(namespace).Delete(context.TODO(), operatorOwnerName, metav1.DeleteOptions{})

		waitForPodTermination(namespace, podLabel, leadingAPI)

		newDeployment := &appsv1.Deployment{
			ObjectMeta: metav1.ObjectMeta{
				Name:      deployment.ObjectMeta.Name,
				Namespace: deployment.ObjectMeta.Namespace,
				Labels:    deployment.ObjectMeta.Labels,
			},
			Spec: deployment.Spec,
		}
		if redirect {
			containersNum := len(newDeployment.Spec.Template.Spec.Containers)
			for i := 0; i < containersNum; i++ {
				envNum := len(newDeployment.Spec.Template.Spec.Containers[i].Env)
				for j := 0; j < envNum; j++ {
					if newDeployment.Spec.Template.Spec.Containers[i].Env[j].Name == "KUBERNETES_SERVICE_HOST" {
						log.Printf("change api to %s\n", followingAPI)
						newDeployment.Spec.Template.Spec.Containers[i].Env[j].Value = followingAPI
						break
					}
				}
			}
		}
		newDeployment, err = clientset.AppsV1().Deployments(namespace).Create(context.TODO(), newDeployment, metav1.CreateOptions{})
		checkError(err)
		log.Println(newDeployment.Spec.Template.Spec.Containers[0].Env)

		waitForPodRunning(namespace, podLabel, leadingAPI)
	} else {
		statefulset, err := clientset.AppsV1().StatefulSets(namespace).Get(context.TODO(), operatorOwnerName, metav1.GetOptions{})
		checkError(err)
		log.Println(statefulset.Spec.Template.Spec.Containers[0].Env)
		clientset.AppsV1().StatefulSets(namespace).Delete(context.TODO(), operatorOwnerName, metav1.DeleteOptions{})

		waitForPodTermination(namespace, podLabel, leadingAPI)

		newStatefulset := &appsv1.StatefulSet{
			ObjectMeta: metav1.ObjectMeta{
				Name:      statefulset.ObjectMeta.Name,
				Namespace: statefulset.ObjectMeta.Namespace,
				Labels:    statefulset.ObjectMeta.Labels,
			},
			Spec: statefulset.Spec,
		}
		if redirect {
			containersNum := len(newStatefulset.Spec.Template.Spec.Containers)
			for i := 0; i < containersNum; i++ {
				envNum := len(newStatefulset.Spec.Template.Spec.Containers[i].Env)
				for j := 0; j < envNum; j++ {
					if newStatefulset.Spec.Template.Spec.Containers[i].Env[j].Name == "KUBERNETES_SERVICE_HOST" {
						log.Printf("change api to %s\n", followingAPI)
						newStatefulset.Spec.Template.Spec.Containers[i].Env[j].Value = followingAPI
						break
					}
				}
			}
		}
		newStatefulset, err = clientset.AppsV1().StatefulSets(namespace).Create(context.TODO(), newStatefulset, metav1.CreateOptions{})
		checkError(err)
		log.Println(newStatefulset.Spec.Template.Spec.Containers[0].Env)

		waitForPodRunning(namespace, podLabel, leadingAPI)
	}
}
