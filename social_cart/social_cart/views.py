__author__ = 'indrajit'

import logging

from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from django.http.response import JsonResponse
from django.shortcuts import Http404, HttpResponse, HttpResponseRedirect
from django.views.generic import View, TemplateView
from django.contrib.auth.decorators import login_required
from django.db.models import Q

from rest_framework.authentication import SessionAuthentication, BasicAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet, ViewSet
from rest_framework.status import HTTP_200_OK, HTTP_400_BAD_REQUEST, HTTP_201_CREATED, HTTP_204_NO_CONTENT, HTTP_307_TEMPORARY_REDIRECT
from rest_framework.decorators import detail_route

from .serializers import (ShopperSerializer, FriendSerializer, GroupMemberSerializer,
                          GroupSerializer, ProductSerializer, CartInviteSerializer, CartItemListSerializer)
from .models import Shopper, Cart, CartItem, CartInvite, Friend, Group, GroupMember, Product

logger = logging.getLogger(__name__)


class BaseApiView(APIView):
    permission_classes = (IsAuthenticated, )


class LoginRequiredMixin(object):
    @classmethod
    def as_view(cls, **initkwargs):
        view = super(LoginRequiredMixin, cls).as_view(**initkwargs)
        return login_required(view, login_url='/login/')


class HomeView(LoginRequiredMixin, TemplateView):
    template_name = 'home.html'

    def get_context_data(self, **kwargs):
        if 'gcm_key' in self.request.session:
            set_gcm_key(self.request.user, self.request.session.pop('gcm_key'))

        context = super(HomeView, self).get_context_data(**kwargs)
        return context


class SocialCartTemplateView(LoginRequiredMixin, TemplateView):
    template_name = 'social_cart.html'

    def get_context_data(self, **kwargs):
        try:
            shopper = Shopper.objects.get(user=self.request.user)
        except Shopper.DoesNotExist as e:
            logger.exception('User Not Found')
            raise Http404

        context = super(SocialCartTemplateView, self).get_context_data(**kwargs)
        try:
            cart = Cart.objects.filter(user=shopper, type='S', is_active=True)[0]
            context.update({'cart': cart.pk})
        except IndexError as e:
            logger.info('No Active cart found')
        return context


class CartInviteTemplateView(LoginRequiredMixin, TemplateView):
    template_name = 'invitees.html'

    def get_context_data(self, **kwargs):
        context = super(CartInviteTemplateView, self).get_context_data(**kwargs)
        return context


class SocialCartInviteeView(BaseApiView):
    """
    View used by all invitees to get social carts and add products
    """
    def get_object(self, user):
        try:
            return Shopper.objects.get(user=user)
        except Shopper.DoesNotExist as e:
            logger.exception('User Not Found')
            raise Http404

    def get(self, request, format=None):
        shopper = self.get_object(request.user)
        social_carts = CartInvite.objects.filter(invitee=shopper, is_active=True)
        serializer = CartInviteSerializer(social_carts, many=True)
        data = serializer.data
        for self_cart in Cart.objects.filter(user=shopper, is_active=True):
            data.append({'get_owner_name': 'My Cart', 'get_cart_id': self_cart.pk})
        return Response({'carts': data}, HTTP_200_OK)

    def post(self, request, format=None):
        shopper = self.get_object(request.user)
        data = request.data
        [d.update({'added_by': shopper.pk}) for d in data]
        serializer = CartItemListSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response({"status": "SUCCESS"}, status=HTTP_201_CREATED)
        return Response(status=HTTP_400_BAD_REQUEST)


class SocialCartShopperView(BaseApiView):
    def get_object(self, user):
        try:
            return Shopper.objects.get(user=user)
        except Shopper.DoesNotExist as e:
            logger.exception('User Not Found')
            raise Http404

    def get_cart(self, request, shopper):
        try:
            if 'cart' in request.GET:
                return Cart.objects.get(pk=request.GET['cart'])
            else:
                    return Cart.objects.filter(user=shopper, is_active=True).order_by('-pk')[0]
        except (IndexError, Cart.DoesNotExist,) as e:
            logger.info('No Cart Found')
            return None

    def get(self, request, format=None):
        shopper = self.get_object(request.user)
        social_cart = self.get_cart(request, shopper)

        if not social_cart:
            logger.exception('No Cart')
            return Response(HTTP_204_NO_CONTENT)

        cart_items = social_cart.cartitems.all()
        products = [cart_item.product for cart_item in cart_items]
        serializer = ProductSerializer(products, many=True)
        data = serializer.data
        for index, cart_item in enumerate(cart_items):
            data[index].update({'added_by': cart_item.added_by.user.username, 'quantity': cart_item.quantity})

        return Response(data, HTTP_200_OK)

    def post(self, request, format=None):
        shopper = self.get_object(request.user)
        social_cart = self.get_cart(request, shopper)
        social_cart.finalize()
        return Response({'status': 'SUCCESS', 'detail': 'Awesome job! Your friends thank you!!'}, status=HTTP_201_CREATED)


class SocialCartHomeView(BaseApiView):
    def get_object(self, user):
        try:
            return Shopper.objects.get(user=user)
        except Shopper.DoesNotExist as e:
            logger.exception('User Not Found')
            raise Http404

    def get(self, request, format=None):
        shopper = self.get_object(request.user)
        social_cart = Cart.objects.filter(user=shopper, is_active=True)
        pass


class LoginView(TemplateView):
    template_name = 'login.html'

    def get_context_data(self, **kwargs):
        context = super(LoginView, self).get_context_data(**kwargs)
        return context

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated():
            return HttpResponseRedirect('/home/')
        return super(LoginView, self).get(request, *args, **kwargs)


class UserSearchView(BaseApiView):
    def get(self, request, format=None):
        try:
            param = self.request.GET['q']
        except KeyError as e:
            raise Http404
        shoppers = Shopper.objects.filter(Q(user__first_name__icontains=param) |
                                                Q(user__last_name__icontains=param) |
                                                Q(user__email__icontains=param) |
                                                Q(user__username__icontains=param))
        serializer = ShopperSerializer(shoppers, many=True)
        return Response(serializer.data, status=HTTP_200_OK)


class FriendsView(BaseApiView):
    def get_object(self, user):
        try:
            return Shopper.objects.get(user=user)
        except Shopper.DoesNotExist as e:
            logger.exception('User Not Found')
            raise Http404

    def get(self, request, format=None):
        user = self.get_object(request.user)
        friends = user.get_friends()
        serializer = ShopperSerializer(friends, many=True)
        return Response(serializer.data, HTTP_200_OK)

    def put(self, request, shopper_id, format=None):
        user = self.get_object(request.user)
        friend = self.get_object(shopper_id)
        friendship = user.add_friend(friend)
        serializer = FriendSerializer(friendship)
        return Response(serializer.data, status=HTTP_201_CREATED)

    def delete(self, request, shopper_id, format=None):
        user = self.get_object(shopper_id)
        friend = self.get_object(shopper_id)
        user.remove_friends(friend)
        return Response({'status': 'SUCCESS', 'detail': 'Removed friend'}, status=HTTP_204_NO_CONTENT)


class ProductsView(BaseApiView):
    def get(self, request, format=None):
        products = Product.objects.all()[:2]
        serializer = ProductSerializer(products, many=True)
        return Response({'products': serializer.data}, HTTP_200_OK)


class GoShopView(BaseApiView):
    """
    Allows the Shopper to Initiate a Social Shopping Event
    """
    def get_object(self, user):
        try:
            return Shopper.objects.get(user=user)
        except Shopper.DoesNotExist as e:
            logger.exception('User Not Found')
            raise Http404

    def get(self, request, format=None):
        shopper = self.get_object(request.user)
        groups = Group.objects.filter(user=shopper)
        group_serializer = GroupSerializer(groups, many=True)
        friends = shopper.get_friends()
        friend_serializer = FriendSerializer(friends, many=True)
        return Response({'friends': friend_serializer.data, 'groups': group_serializer.data}, HTTP_200_OK)

    def post(self, request, format=None):
        shopper = self.get_object(request.user)
        cart, created = Cart.objects.update_or_create(user=shopper, type='S', is_active=True,
                                             defaults={"user": shopper, "type": "S", "is_active": True})

        friend_ids = group_ids = []
        if 'friends' in request.data:
            friend_ids = request.data['friends']
        if 'groups' in request.data:
            group_ids = request.data['groups']
        notify_set = set(friend_ids)
        logger.info('friends: {} groups: {}'.format(friend_ids, group_ids))
        for group_id in group_ids:
            try:
                group = Group.objects.get(pk=group_id)
                logger.info("Invited Group ID: {}".format(group))
                for friend in group.get_members:
                    notify_set.add(friend['pk'])
            except Group.DoesNotExist as e:
                logger.exception("Bad Group PK: {}".format(group_id))

        for friend_id in notify_set:
            try:
                friend = Shopper.objects.get(pk=friend_id)
            except Friend.DoesNotExist as e:
                logger.exception('Friend Not Exist')
                continue

            CartInvite.objects.create(owner=shopper, cart=cart, invitee=friend, is_active=True)
            friend.notify_cart_created(cart)

        return Response({'status': 'SUCCESS'}, HTTP_201_CREATED)

class GroupViewSet(BaseApiView, ModelViewSet):
    serializer_class = GroupSerializer

    def get_queryset(self):
        user = self.get_shopper(self.request.user)
        groups = Group.objects.filter(user=user)
        return groups

    def get_shopper(self, shopper_id):
        try:
            return Shopper.objects.get(user=shopper_id)
        except Shopper.DoesNotExist as e:
            logger.exception('User Not Found')
            raise Http404

    def get_object(self, user, group_id):
        try:
            return Group.objects.get(user=user, pk=group_id)
        except Shopper.DoesNotExist as e:
            logger.exception('Group Not Found')
            raise Http404

    def retrieve(self, request, format=None):
        groups = self.get_queryset()
        serializer = self.get_serializer_class(groups, many=True)
        return Response(serializer.data, status=HTTP_200_OK)

    def create(self, request, format=None):
        data = request.data
        data.update({'user': self.get_shopper(request.user).pk})
        serializer = GroupSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
        return Response(serializer.data, HTTP_201_CREATED)

    @detail_route(methods=['put'])
    def add_list_friend(self, request, pk, format=None):
        user = self.get_shopper(request.user)
        group = self.get_object(user, pk)
        try:
            friend = self.get_shopper(request.data['friend'])
            if not user.is_friends(friend):
                raise ValueError
            member = GroupMember.objects.create(group=group, user=friend)
            serializer = GroupMemberSerializer(member)
            return Response(serializer.data, HTTP_201_CREATED)
        except KeyError as e:
            logger.info('Friend parameter missing')
            raise Http404
        except ValueError as e:
            logger.exception('User is not in friends list')
            raise Http404
        except Shopper.DoesNotExist as e:
            logger.exception(e)
            raise Http404

    @detail_route(methods=['delete'])
    def delete_list_friend(self, request, pk, format=None):
        user = self.get_shopper(request.user)
        group = self.get_object(user, pk)
        try:
            friend = self.get_shopper(self.request.GET['friend'])
            if not user.is_friends(friend):
                raise ValueError
            GroupMember.objects.filter(group=group, user=friend).delete()
            return Response({'status': 'SUCCESS', 'detail': 'Successfully removed from List'}, HTTP_204_NO_CONTENT)
        except KeyError as e:
            logger.info('Friend parameter missing')
            raise Http404
        except ValueError as e:
            logger.exception('User is not in friends list')
            raise Http404


def login_redirect_view(request):
    if request.user.is_authenticated():
        if 'gcm_key' in request.GET:
            set_gcm_key(request.user, request.GET['gcm_key'])
        return HttpResponseRedirect('/home/')
    else:
        if 'gcm_key' in request.GET:
            request.session['gcm_key'] = request.GET['gcm_key']
        return HttpResponseRedirect('/login/')

def gcm_key_view(request):
    if not request.user.is_authenticated():
        logger.exception('Not Logged in')
        return JsonResponse({'status': 'FAIL'})
    if 'gcm_key' not in request.GET:
        logger.exception('Missing Key')
        raise Http404
    user = request.user
    shopper = Shopper.objects.get(user=user)
    shopper.gcm_key = request.GET['gcm_key']
    shopper.save()
    return JsonResponse({'status': 'SUCCESS'})


def set_gcm_key(user, gcm_key):
    try:
        shopper = Shopper.objects.get(user=user)
        shopper.gcm_key = gcm_key
        shopper.save()
    except Exception as e:
        logger.exception(e)
